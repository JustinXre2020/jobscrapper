"""Base class for all agent nodes.

Provides shared infrastructure:
    - LLM client injection
    - _job_context(job)  — human-readable log label
    - _structured_with_fallback(messages, model_class)  — structured LLM call with JSON-repair fallback
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, TypeVar

from loguru import logger
from pydantic import BaseModel

from infra.llm_client import BaseLLMClient, LLMClientError
from infra.json_repair import repair_json


T = TypeVar("T", bound=BaseModel)


class BaseNode(ABC):
    """Abstract base for LangGraph agent nodes."""

    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    @abstractmethod
    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute this node and return state updates."""

    def _job_context(self, job: Dict[str, Any]) -> str:
        """Return a short human-readable label for log messages."""
        title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")
        return f"{title} @ {company}"

    async def _structured_with_fallback(
        self,
        messages: List[Dict[str, str]],
        model_class: Type[T],
        job_context: Optional[str] = None,
    ) -> T:
        """Call LLM for structured output; fall back to text + JSON repair on failure.

        Args:
            messages: Chat messages with 'role' and 'content'.
            model_class: Pydantic model class to parse the response into.
            job_context: Optional label used in log messages.

        Returns:
            Validated instance of model_class.

        Raises:
            LLMClientError: When both structured and text-mode calls fail.
            ValueError: When JSON repair cannot produce a valid model instance.
        """
        try:
            return await self.llm_client.complete_structured(
                messages, model_class, job_context=job_context
            )
        except LLMClientError:
            logger.warning(
                f"Structured output failed [{job_context}], falling back to text+JSON repair"
            )

        response_text = await self.llm_client.complete_text(
            messages, job_context=job_context
        )
        repaired = repair_json(response_text)
        data = json.loads(repaired)
        return model_class.model_validate(data)
