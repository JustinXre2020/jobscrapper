"""Provider-agnostic async LLM client.

Wraps AsyncOpenAI + instructor for structured output.
To migrate to a different provider (e.g., GLM), change only this file.
"""

import asyncio
import os
import logging
from typing import Any, Dict, List, Optional, Type, TypeVar

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel
import instructor

load_dotenv()

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Transient HTTP errors worth retrying (gateway/server-side failures)
_RETRYABLE_CODES = ("502", "503", "504")
_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 5.0  # seconds, doubles each retry


class LLMClientError(Exception):
    """Raised on LLM API errors (rate limiting, network, etc.)."""
    pass


def _is_retryable(error_str: str) -> bool:
    """Check if an error string indicates a transient server-side failure."""
    return any(code in error_str for code in _RETRYABLE_CODES)


class LLMClient:
    """Provider-agnostic async LLM client using AsyncOpenAI + instructor.

    Reads configuration from environment variables:
        OPENROUTER_API_URL  - API base URL (default: https://openrouter.ai/api/v1)
        OPENROUTER_API_KEY  - API key (required)
        OPENROUTER_MODEL    - Model identifier (default: liquid/lfm-2.5-1.2b-instruct:free)
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

        # Raw client for text-mode calls (complete_text)
        self._raw_client = AsyncOpenAI(
            base_url=self.api_url,
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://resume-matcher.app",
                "X-Title": "JobsWrapper-Filter",
            },
            timeout=60.0,
        )
        # Instructor-wrapped client for structured output (complete_structured)
        self._instructor_client: Any = instructor.from_openai(
            self._raw_client, mode=instructor.Mode.JSON
        )

    async def complete_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        job_context: Optional[str] = None,
    ) -> T:
        """Call the LLM and return a validated Pydantic instance.

        Retries automatically on transient 502/503/504 errors.

        Args:
            messages: Chat messages with 'role' and 'content'.
            response_model: Pydantic model class for structured output.
            job_context: Optional label for logging.

        Returns:
            Validated Pydantic instance.

        Raises:
            LLMClientError: On API failures including rate limiting.
        """
        context_str = f" [{job_context}]" if job_context else ""
        user_prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
        logger.debug(f"LLM_STRUCTURED{context_str}:\n{'-'*60}\n{user_prompt[:500]}\n{'-'*60}")

        last_error: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._instructor_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_model=response_model,
                )
                return response
            except Exception as e:
                last_error = e
                error_str = str(e)

                # Rate limit — don't retry, fail immediately
                if "429" in error_str or "rate" in error_str.lower():
                    logger.error(f"LLM rate limited{context_str}: {error_str}")
                    raise LLMClientError("Rate limited (429)") from e

                # Transient server error — retry with backoff
                if _is_retryable(error_str) and attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"LLM transient error{context_str} (attempt {attempt + 1}/"
                        f"{_MAX_RETRIES + 1}): {error_str}, retrying in {delay:.0f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

                # Non-retryable or retries exhausted
                logger.error(f"LLM API error{context_str}: {error_str}")
                raise LLMClientError(f"API request failed: {error_str}") from e

        # Should not reach here, but just in case
        raise LLMClientError(f"API request failed after {_MAX_RETRIES + 1} attempts") from last_error

    async def complete_text(
        self,
        messages: List[Dict[str, str]],
        job_context: Optional[str] = None,
    ) -> str:
        """Call the LLM and return raw text response.

        Retries automatically on transient 502/503/504 errors.

        Args:
            messages: Chat messages with 'role' and 'content'.
            job_context: Optional label for logging.

        Returns:
            Raw text response string.

        Raises:
            LLMClientError: On API failures including rate limiting.
        """
        context_str = f" [{job_context}]" if job_context else ""
        user_prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
        logger.debug(f"LLM_TEXT{context_str}:\n{'-'*60}\n{user_prompt[:500]}\n{'-'*60}")

        last_error: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._raw_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
                error_str = str(e)

                if "429" in error_str or "rate" in error_str.lower():
                    logger.error(f"LLM rate limited{context_str}: {error_str}")
                    raise LLMClientError("Rate limited (429)") from e

                if _is_retryable(error_str) and attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"LLM transient error{context_str} (attempt {attempt + 1}/"
                        f"{_MAX_RETRIES + 1}): {error_str}, retrying in {delay:.0f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error(f"LLM API error{context_str}: {error_str}")
                raise LLMClientError(f"API request failed: {error_str}") from e

        raise LLMClientError(f"API request failed after {_MAX_RETRIES + 1} attempts") from last_error
