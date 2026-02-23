"""Provider-agnostic async LLM client.

Architecture:
    BaseLLMClient (ABC)
        OpenRouterClient  -- calls OpenRouter via AsyncOpenAI + instructor
        LocalInferenceClient  -- calls a local OpenAI-compatible endpoint (e.g. Ollama)

Factory:
    create_llm_client(provider, model) -> BaseLLMClient

Backwards compat:
    LLMClient = OpenRouterClient  (drop-in replacement for existing code)
"""

import asyncio
import os
from abc import ABC, abstractmethod
from loguru import logger
from typing import Any, Dict, List, Optional, Type, TypeVar

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel
import instructor

load_dotenv()


T = TypeVar("T", bound=BaseModel)

# Transient HTTP errors worth retrying (gateway/server-side failures)
_RETRYABLE_CODES = ("502", "503", "504")
_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 5.0  # seconds, doubles each retry


class LLMClientError(Exception):
    """Raised on LLM API errors (rate limiting, network, etc.)."""
    pass


def _is_retryable(error_str: str) -> bool:
    """Return True if the error string signals a transient server-side failure."""
    return any(code in error_str for code in _RETRYABLE_CODES)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class BaseLLMClient(ABC):
    """Interface every LLM provider implementation must satisfy.

    Agent nodes depend only on this interface, not on any concrete class.
    Swap providers by passing a different implementation at graph build time.
    """

    model: str
    temperature: float
    max_tokens: int

    @abstractmethod
    async def complete_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        job_context: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> T:
        """Call the LLM and return a validated Pydantic instance.

        Args:
            messages: Chat messages with 'role' and 'content'.
            response_model: Pydantic model class for the structured response.
            job_context: Optional label for log messages.
            temperature: Per-call temperature override.

        Returns:
            Validated instance of response_model.

        Raises:
            LLMClientError: On API failures including rate limiting.
        """

    @abstractmethod
    async def complete_text(
        self,
        messages: List[Dict[str, str]],
        job_context: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Call the LLM and return the raw text response.

        Args:
            messages: Chat messages with 'role' and 'content'.
            job_context: Optional label for log messages.
            temperature: Per-call temperature override.

        Returns:
            Raw text content from the model.

        Raises:
            LLMClientError: On API failures including rate limiting.
        """


# ---------------------------------------------------------------------------
# Shared retry mixin
# ---------------------------------------------------------------------------

class _RetryMixin:
    """Shared retry / backoff logic extracted from both implementations."""

    _max_retries: int = _MAX_RETRIES
    _retry_base_delay: float = _RETRY_BASE_DELAY

    def _handle_error(
        self,
        e: Exception,
        attempt: int,
        context_str: str,
    ) -> Optional[float]:
        """Classify an exception and return the retry delay, or raise.

        Returns the sleep duration if the call should be retried, raises otherwise.
        """
        error_str = str(e)

        # Rate limit — fail immediately, no retry
        if "429" in error_str or "rate" in error_str.lower():
            logger.error(f"LLM rate limited{context_str}: {error_str}")
            raise LLMClientError("Rate limited (429)") from e

        # Transient server error — retry with backoff
        if _is_retryable(error_str) and attempt < self._max_retries:
            delay = self._retry_base_delay * (2 ** attempt)
            logger.warning(
                f"LLM transient error{context_str} (attempt {attempt + 1}/"
                f"{self._max_retries + 1}): {error_str}, retrying in {delay:.0f}s"
            )
            return delay

        # Non-retryable
        logger.error(f"LLM API error{context_str}: {error_str}")
        raise LLMClientError(f"API request failed: {error_str}") from e


# ---------------------------------------------------------------------------
# OpenRouter implementation
# ---------------------------------------------------------------------------

class OpenRouterClient(_RetryMixin, BaseLLMClient):
    """Calls OpenRouter via AsyncOpenAI + instructor.

    Reads configuration from environment variables:
        OPENROUTER_API_URL  -- API base URL (default: https://openrouter.ai/api/v1)
        OPENROUTER_API_KEY  -- API key (required)
        OPENROUTER_MODEL    -- Model identifier (default: liquid/lfm-2.5-1.2b-instruct:free)
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> None:
        self.api_url = api_url or os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1")
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.model = model or os.getenv("OPENROUTER_MODEL", "liquid/lfm-2.5-1.2b-instruct:free")
        self.temperature = temperature
        self.max_tokens = max_tokens

        if not self.api_key:
            raise LLMClientError("OPENROUTER_API_KEY environment variable not set")

        # Raw client for text-mode calls
        self._raw_client = AsyncOpenAI(
            base_url=self.api_url,
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://resume-matcher.app",
                "X-Title": "JobsWrapper-Filter",
            },
            timeout=60.0,
        )
        # Instructor-wrapped client for structured output
        self._instructor_client: Any = instructor.from_openai(
            self._raw_client, mode=instructor.Mode.JSON
        )

    async def complete_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        job_context: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> T:
        """Call the LLM and return a validated Pydantic instance."""
        effective_temp = temperature if temperature is not None else self.temperature
        context_str = f" [{job_context}]" if job_context else ""
        user_prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
        logger.debug(f"LLM_STRUCTURED{context_str}:\n{'-'*60}\n{user_prompt[:500]}\n{'-'*60}")

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._instructor_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=effective_temp,
                    max_tokens=self.max_tokens,
                    response_model=response_model,
                )
                return response
            except Exception as e:
                last_error = e
                delay = self._handle_error(e, attempt, context_str)
                if delay is not None:
                    await asyncio.sleep(delay)

        raise LLMClientError(
            f"API request failed after {self._max_retries + 1} attempts"
        ) from last_error

    async def complete_text(
        self,
        messages: List[Dict[str, str]],
        job_context: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Call the LLM and return the raw text response."""
        effective_temp = temperature if temperature is not None else self.temperature
        context_str = f" [{job_context}]" if job_context else ""
        user_prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
        logger.debug(f"LLM_TEXT{context_str}:\n{'-'*60}\n{user_prompt[:500]}\n{'-'*60}")

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._raw_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=effective_temp,
                    max_tokens=self.max_tokens,
                )
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
                delay = self._handle_error(e, attempt, context_str)
                if delay is not None:
                    await asyncio.sleep(delay)

        raise LLMClientError(
            f"API request failed after {self._max_retries + 1} attempts"
        ) from last_error


# ---------------------------------------------------------------------------
# Local inference implementation
# ---------------------------------------------------------------------------

class LocalInferenceClient(_RetryMixin, BaseLLMClient):
    """Calls a local OpenAI-compatible inference server (e.g. Ollama, llama.cpp).

    Reads configuration from environment variables:
        LOCAL_LLM_API_URL  -- Base URL of the local server (default: http://localhost:11434/v1)
        LOCAL_LLM_API_KEY  -- API key if the local server requires one (default: "local")
        LOCAL_LLM_MODEL    -- Model name as known to the server (default: "xiaomi")
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> None:
        self.api_url = api_url or os.getenv("LOCAL_LLM_API_URL", "http://localhost:11434/v1")
        # Local servers often accept any non-empty key value
        self.api_key = api_key or os.getenv("LOCAL_LLM_API_KEY", "local")
        self.model = model or os.getenv("LOCAL_LLM_MODEL", "xiaomi")
        self.temperature = temperature
        self.max_tokens = max_tokens

        self._raw_client = AsyncOpenAI(
            base_url=self.api_url,
            api_key=self.api_key,
            timeout=120.0,  # local inference can be slower
        )
        self._instructor_client: Any = instructor.from_openai(
            self._raw_client, mode=instructor.Mode.JSON
        )
        logger.info(f"LocalInferenceClient: {self.api_url} | model={self.model}")

    async def complete_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        job_context: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> T:
        """Call the local model and return a validated Pydantic instance."""
        effective_temp = temperature if temperature is not None else self.temperature
        context_str = f" [{job_context}]" if job_context else ""
        user_prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
        logger.debug(
            f"LOCAL_STRUCTURED{context_str}:\n{'-'*60}\n{user_prompt[:500]}\n{'-'*60}"
        )

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._instructor_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=effective_temp,
                    max_tokens=self.max_tokens,
                    response_model=response_model,
                )
                return response
            except Exception as e:
                last_error = e
                delay = self._handle_error(e, attempt, context_str)
                if delay is not None:
                    await asyncio.sleep(delay)

        raise LLMClientError(
            f"Local API request failed after {self._max_retries + 1} attempts"
        ) from last_error

    async def complete_text(
        self,
        messages: List[Dict[str, str]],
        job_context: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Call the local model and return the raw text response."""
        effective_temp = temperature if temperature is not None else self.temperature
        context_str = f" [{job_context}]" if job_context else ""
        user_prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
        logger.debug(f"LOCAL_TEXT{context_str}:\n{'-'*60}\n{user_prompt[:500]}\n{'-'*60}")

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._raw_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=effective_temp,
                    max_tokens=self.max_tokens,
                )
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
                delay = self._handle_error(e, attempt, context_str)
                if delay is not None:
                    await asyncio.sleep(delay)

        raise LLMClientError(
            f"Local API request failed after {self._max_retries + 1} attempts"
        ) from last_error


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_llm_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0,
    max_tokens: int = 8192,
) -> BaseLLMClient:
    """Instantiate the right LLM client for a given provider name.

    Args:
        provider: "openrouter" or "local". Falls back to the OPENROUTER_API_KEY env var
                  presence to auto-detect when None.
        model: Optional model override. Uses provider-specific env defaults when None.
        temperature: Default sampling temperature.
        max_tokens: Maximum token budget per call.

    Returns:
        A concrete BaseLLMClient implementation.
    """
    if provider is None:
        # Auto-detect: use local when no OpenRouter key is configured
        provider = "openrouter" if os.getenv("OPENROUTER_API_KEY") else "local"

    if provider == "local":
        return LocalInferenceClient(model=model, temperature=temperature, max_tokens=max_tokens)
    if provider == "openrouter":
        return OpenRouterClient(model=model, temperature=temperature, max_tokens=max_tokens)

    raise ValueError(
        f"Unknown LLM provider '{provider}'. Supported values: 'openrouter', 'local'."
    )


# ---------------------------------------------------------------------------
# Backwards-compat alias
# ---------------------------------------------------------------------------

#: Alias kept so existing imports of `LLMClient` continue to work without changes.
LLMClient = OpenRouterClient
