"""Summarizer node - extracts structured data from raw job descriptions."""

import json
import logging
from typing import Any, Dict

import pandas as pd

from infra.llm_client import LLMClient, LLMClientError
from infra.models import JobSummaryModel
from infra.json_repair import repair_json
from agent.state import AgentState
from agent.prompts.summarizer_prompt import SUMMARIZER_SYSTEM, build_summarizer_prompt

logger = logging.getLogger(__name__)


def _safe_str(value: Any, default: str = "") -> str:
    """Safely convert value to string, handling NaN/None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return str(value)


async def summarizer_node(state: AgentState, llm_client: LLMClient) -> Dict[str, Any]:
    """Node 1: Extract structured summary from raw job posting.

    Args:
        state: Current agent state with job and search_terms.
        llm_client: Provider-agnostic LLM client.

    Returns:
        State updates: summary, or skipped/error flags.
    """
    job = state["job"]
    search_terms = state["search_terms"]
    job_title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    job_context = f"{job_title} @ {company}"

    # On redo passes, summary is already populated — skip re-extraction
    existing_summary = state.get("summary")
    if existing_summary:
        logger.debug(f"Skipping summarizer for {job_context} — summary already exists (redo pass)")
        return {"summary": existing_summary}

    # Skip jobs with no/short description
    desc = _safe_str(job.get("description"), "")
    if not desc or len(desc) < 50:
        logger.debug(f"Skipping {job_context} - description too short ({len(desc)} chars)")
        return {"skipped": True, "error": f"Description too short ({len(desc)} chars)"}

    try:
        prompt = build_summarizer_prompt(job, search_terms)
        messages = [
            {"role": "system", "content": SUMMARIZER_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        try:
            summary_model = await llm_client.complete_structured(
                messages, JobSummaryModel, job_context=job_context
            )
            logger.info(f"SUMMARY [{job_context}]: {summary_model}")
            summary_dict = summary_model.model_dump()
        except (LLMClientError, Exception) as struct_err:
            # Structured output failed (often due to invalid JSON escapes from
            # models like Liquid AI), fall back to text mode + JSON repair.
            logger.warning(
                f"Structured output failed [{job_context}]: {struct_err}, "
                "falling back to text + JSON repair"
            )
            response_text = await llm_client.complete_text(messages, job_context=job_context)
            repaired = repair_json(response_text)
            raw = json.loads(repaired)
            summary_model = JobSummaryModel.model_validate(raw)
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
        logger.error(f"Summarizer unexpected error [{job_context}]: {e}", exc_info=True)
        return {"error": str(e)}
