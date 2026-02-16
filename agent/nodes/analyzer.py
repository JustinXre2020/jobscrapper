"""Analyzer node - evaluates job against criteria using structured summary data."""

import json
import logging
from typing import Any, Dict

from infra.llm_client import LLMClient, LLMClientError
from infra.models import JobEvaluation
from infra.json_repair import repair_json
from agent.state import AgentState
from agent.prompts.analyzer_prompt import ANALYZER_SYSTEM, build_analyzer_prompt

logger = logging.getLogger(__name__)


def _parse_text_fallback(response_text: str) -> Dict[str, Any]:
    """Parse LLM text response into evaluation dict (fallback for structured mode failure).

    Uses JSON repair to handle invalid escape sequences from models like Liquid AI.
    """
    try:
        repaired = repair_json(response_text)
        result = json.loads(repaired)
        return {
            "keyword_match": result.get("keyword_match", True),
            "visa_sponsorship": result.get("visa_sponsorship", True),
            "entry_level": result.get("entry_level", True),
            "requires_phd": result.get("requires_phd", False),
            "is_internship": result.get("is_internship", False),
            "reason": result.get("reason", ""),
        }
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: default to permissive
    return {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": True,
        "requires_phd": False,
        "is_internship": False,
        "reason": "JSON parse error - defaulting to pass",
    }


async def analyzer_node(state: AgentState, llm_client: LLMClient) -> Dict[str, Any]:
    """Node 2: Evaluate job against filter criteria using structured summary.

    Args:
        state: Current agent state with summary, search_terms, feedback.
        llm_client: Provider-agnostic LLM client.

    Returns:
        State updates: evaluation dict, incremented retry_count on retry.
    """
    summary = state.get("summary")
    search_terms = state["search_terms"]
    accumulated_feedback = state.get("accumulated_feedback", [])
    review_feedback = state.get("review_feedback")
    job = state["job"]
    job_title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    job_context = f"{job_title} @ {company}"

    if not summary:
        return {"error": "No summary available for analysis"}

    # Track retries
    retry_count = state.get("retry_count", 0)
    if review_feedback:
        retry_count += 1

    try:
        prompt = build_analyzer_prompt(
            summary,
            search_terms,
            accumulated_feedback=accumulated_feedback,
            review_feedback=review_feedback,
        )
        messages = [
            {"role": "system", "content": ANALYZER_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        try:
            evaluation_model = await llm_client.complete_structured(
                messages, JobEvaluation, job_context=job_context
            )
            result = evaluation_model.model_dump()
        except LLMClientError:
            # Structured output failed, try text mode fallback
            logger.warning(f"Structured output failed [{job_context}], falling back to text")
            response_text = await llm_client.complete_text(messages, job_context=job_context)
            result = _parse_text_fallback(response_text)

        result["job_title"] = job_title
        result["company"] = company

        logger.info(
            f"EVALUATED [{job_context}]: "
            f"keyword={result.get('keyword_match')}, "
            f"visa={result.get('visa_sponsorship')}, "
            f"entry={result.get('entry_level')}, "
            f"phd={result.get('requires_phd')}, "
            f"intern={result.get('is_internship')}"
            f"{' (RETRY)' if review_feedback else ''}"
        )

        return {
            "evaluation": result,
            "retry_count": retry_count,
            "review_feedback": None,  # Clear feedback after consuming it
        }

    except LLMClientError as e:
        logger.warning(f"Analyzer LLM error [{job_context}]: {e}")
        if "429" in str(e) or "Rate limited" in str(e):
            return {
                "evaluation": {
                    "keyword_match": False,
                    "visa_sponsorship": False,
                    "entry_level": False,
                    "requires_phd": True,
                    "is_internship": True,
                    "reason": "Rate limited (429) - filtered out",
                    "error": True,
                    "rate_limited": True,
                    "job_title": job_title,
                    "company": company,
                },
                "error": "Rate limited",
            }
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Analyzer unexpected error [{job_context}]: {e}", exc_info=True)
        return {"error": str(e)}
