"""Summarizer node — extracts structured data from raw job descriptions.

Public interface:
    SummarizerNode(BaseNode)  — class-based, injectable LLM client
    summarizer_node(state, llm_client)  — module-level shim for backwards compat
"""

import os
from loguru import logger
from typing import Any, Dict, Optional

import pandas as pd

from infra.llm_client import BaseLLMClient, LLMClientError, create_llm_client
from infra.models import JobSummaryModel
from agent.state import AgentState
from agent.nodes.base import BaseNode
from agent.prompts.summarizer_prompt import SUMMARIZER_SYSTEM, build_summarizer_prompt


def _safe_str(value: Any, default: str = "") -> str:
    """Safely convert value to string, handling NaN/None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return str(value)


def _build_summarizer_client() -> BaseLLMClient:
    """Construct the LLM client for Summarizer from env vars.

    Env vars (all optional):
        SUMMARIZER_PROVIDER  -- 'local' or 'openrouter' (default: 'local')
        SUMMARIZER_MODEL     -- model name (default: provider-specific default)
    """
    provider = os.getenv("SUMMARIZER_PROVIDER", "local")
    model = os.getenv("SUMMARIZER_MODEL") or None  # None → provider default
    return create_llm_client(provider=provider, model=model)


class SummarizerNode(BaseNode):
    """LangGraph node that extracts a structured JobSummaryModel from a raw posting.

    Uses the Xiaomi / local model by default. Inject a different ``BaseLLMClient``
    for testing or to switch providers at runtime.
    """

    def __init__(self, llm_client: Optional[BaseLLMClient] = None) -> None:
        """
        Args:
            llm_client: LLM provider to use. When None, reads SUMMARIZER_PROVIDER /
                        SUMMARIZER_MODEL env vars to build a default client.
        """
        super().__init__(llm_client or _build_summarizer_client())

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        """Extract structured summary from raw job posting.

        Args:
            state: Current agent state with 'job' and 'search_terms'.

        Returns:
            State updates: {'summary': dict} on success, or {'skipped': True, 'error': ...}.
        """
        job = state["job"]
        search_terms = state["search_terms"]
        job_context = self._job_context(job)

        # On redo passes the summary is already populated — skip re-extraction
        existing_summary = state.get("summary")
        if existing_summary:
            logger.debug(f"Skipping summarizer for {job_context} — already summarized (redo)")
            return {"summary": existing_summary}

        # Skip jobs with no/very short description
        desc = _safe_str(job.get("description"), "")
        if not desc or len(desc) < 50:
            logger.debug(f"Skipping {job_context} — description too short ({len(desc)} chars)")
            return {"skipped": True, "error": f"Description too short ({len(desc)} chars)"}

        try:
            prompt = build_summarizer_prompt(job, search_terms)
            messages = [
                {"role": "system", "content": SUMMARIZER_SYSTEM},
                {"role": "user", "content": prompt},
            ]

            # Structured call with automatic text + JSON-repair fallback (via BaseNode)
            summary_model = await self._structured_with_fallback(
                messages, JobSummaryModel, job_context=job_context
            )
            summary_dict = summary_model.model_dump()

            logger.info(
                f"SUMMARIZED [{job_context}]: "
                f"role={summary_dict.get('role_type')}, "
                f"seniority={summary_dict.get('seniority_level')}, "
                f"yrs={summary_dict.get('years_experience_required')}"
            )
            return {"summary": summary_dict}

        except LLMClientError as e:
            logger.warning(f"Summarizer LLM error [{job_context}]: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Summarizer unexpected error [{job_context}]: {e}")
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Backwards-compat shim — existing callers that pass `llm_client` explicitly
# ---------------------------------------------------------------------------

async def summarizer_node(state: AgentState, llm_client: BaseLLMClient) -> Dict[str, Any]:
    """Module-level wrapper kept for backwards compatibility.

    Prefer instantiating ``SummarizerNode`` directly.
    """
    return await SummarizerNode(llm_client)(state)
