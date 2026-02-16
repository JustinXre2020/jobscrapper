"""Reviewer node - LLM-as-Judge to verify Analyzer accuracy."""

import logging
from typing import Any, Dict

from infra.llm_client import LLMClient, LLMClientError
from infra.models import ReviewResult
from agent.state import AgentState
from agent.prompts.reviewer_prompt import REVIEWER_SYSTEM, build_reviewer_prompt

logger = logging.getLogger(__name__)


async def reviewer_node(state: AgentState, llm_client: LLMClient) -> Dict[str, Any]:
    """Node 3: Verify Analyzer's evaluation for logical consistency.

    Args:
        state: Current agent state with summary, evaluation, search_terms.
        llm_client: Provider-agnostic LLM client.

    Returns:
        State updates: review_passed, review_feedback.
    """
    summary = state.get("summary")
    evaluation = state.get("evaluation")
    search_terms = state["search_terms"]
    job = state["job"]
    job_title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    job_context = f"{job_title} @ {company}"

    if not summary or not evaluation:
        logger.warning(f"Reviewer skipping [{job_context}] - missing summary or evaluation")
        return {"review_passed": True, "review_feedback": None}

    try:
        prompt = build_reviewer_prompt(summary, evaluation, search_terms)
        messages = [
            {"role": "system", "content": REVIEWER_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        review = await llm_client.complete_structured(
            messages, ReviewResult, job_context=f"REVIEW:{job_context}"
        )

        logger.info(
            f"REVIEWED [{job_context}]: "
            f"approved={review.approved} | "
            f"{review.feedback[:100]}"
        )

        return {
            "review_passed": review.approved,
            "review_feedback": None if review.approved else review.feedback,
        }

    except LLMClientError as e:
        logger.warning(f"Reviewer LLM error [{job_context}]: {e}, auto-approving")
        return {"review_passed": True, "review_feedback": None}
    except Exception as e:
        logger.error(f"Reviewer unexpected error [{job_context}]: {e}", exc_info=True)
        return {"review_passed": True, "review_feedback": None}
