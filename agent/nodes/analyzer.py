"""Analyzer node - evaluates job against criteria using structured summary data."""

import json
import logging
from typing import Any, Dict, List, Optional

from infra.llm_client import LLMClient, LLMClientError
from infra.models import JobEvaluation
from infra.json_repair import repair_json
from agent.state import AgentState
from agent.prompts.analyzer_prompt import ANALYZER_SYSTEM, build_analyzer_prompt

logger = logging.getLogger(__name__)


def _deterministic_eval(
    summary: Dict[str, Any], search_terms: list[str]
) -> Dict[str, Optional[bool]]:
    """Rule-based evaluation for unambiguous cases. Returns None for fields needing LLM."""
    result: Dict[str, Optional[bool]] = {}

    # visa_sponsorship: empty -> True, explicit denial phrases -> False
    visa = summary.get("visa_statements", [])
    if not visa:
        result["visa_sponsorship"] = True
    else:
        denial_phrases = [
            "must be", "no visa", "without sponsorship",
            "u.s. person", "us citizen", "u.s. citizen",
            "without the need for", "not available",
        ]
        has_denial = any(
            any(d in stmt.lower() for d in denial_phrases) for stmt in visa
        )
        result["visa_sponsorship"] = not has_denial

    # is_internship: directly from summary + title keywords
    is_intern = summary.get("is_internship_coop", False)
    title = (summary.get("title_normalized") or "").lower()
    intern_words = ["intern", "internship", "co-op", "fellowship", "apprenticeship"]
    result["is_internship"] = is_intern or any(w in title for w in intern_words)

    # requires_phd: directly from education field
    result["requires_phd"] = summary.get("education_required") == "phd"

    # entry_level: deterministic for clear cases
    years = summary.get("years_experience_required")
    seniority = summary.get("seniority_level", "unknown")
    senior_levels = {"mid", "senior", "lead", "staff", "principal", "director", "vp"}
    if seniority in senior_levels:
        result["entry_level"] = False
    elif isinstance(years, (int, float)) and years >= 2:
        result["entry_level"] = False
    elif seniority in ("entry", "intern") and (years is None or years <= 1):
        result["entry_level"] = True
    else:
        result["entry_level"] = None  # ambiguous -- let LLM decide

    # keyword_match: requires semantic judgment, leave to LLM
    result["keyword_match"] = None

    return result


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


async def _call_llm_analyzer(
    summary: Dict[str, Any],
    search_terms: List[str],
    accumulated_feedback: List[str],
    llm_client: LLMClient,
    job: Dict[str, Any],
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    """Reusable async helper that calls the LLM analyzer once.

    Args:
        summary: Structured JobSummaryModel data (dict).
        search_terms: Target roles to match.
        accumulated_feedback: Historic corrections.
        llm_client: Provider-agnostic LLM client.
        job: Raw job dict (for logging context).
        temperature: Optional temperature override for this call.

    Returns:
        Evaluation dict with boolean fields and reason.

    Raises:
        LLMClientError: On API failures.
    """
    job_title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    job_context = f"{job_title} @ {company}"

    prompt = build_analyzer_prompt(
        summary,
        search_terms,
        accumulated_feedback=accumulated_feedback,
        job=job,
    )
    messages = [
        {"role": "system", "content": ANALYZER_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    try:
        evaluation_model = await llm_client.complete_structured(
            messages, JobEvaluation, job_context=job_context, temperature=temperature
        )
        return evaluation_model.model_dump()
    except LLMClientError:
        logger.warning(f"Structured output failed [{job_context}], falling back to text")
        response_text = await llm_client.complete_text(
            messages, job_context=job_context, temperature=temperature
        )
        return _parse_text_fallback(response_text)


async def analyzer_node(state: AgentState, llm_client: LLMClient) -> Dict[str, Any]:
    """Node 2: Evaluate job against filter criteria using structured summary."""
    summary = state.get("summary")
    search_terms = state["search_terms"]
    accumulated_feedback = state.get("accumulated_feedback", [])
    job = state["job"]
    job_title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    job_context = f"{job_title} @ {company}"

    if not summary:
        return {"error": "No summary available for analysis"}

    try:
        deterministic = _deterministic_eval(summary, search_terms)

        result = await _call_llm_analyzer(
            summary,
            search_terms,
            accumulated_feedback,
            llm_client,
            job,
        )

        # Override LLM results with deterministic values where available
        for field, value in deterministic.items():
            if value is not None and result.get(field) != value:
                logger.debug(
                    f"Deterministic override [{job_context}]: "
                    f"{field} {result.get(field)} -> {value}"
                )
                result[field] = value

        result["job_title"] = job_title
        result["company"] = company

        logger.info(
            f"EVALUATED [{job_context}]: "
            f"keyword={result.get('keyword_match')}, "
            f"visa={result.get('visa_sponsorship')}, "
            f"entry={result.get('entry_level')}, "
            f"phd={result.get('requires_phd')}, "
            f"intern={result.get('is_internship')}"
        )

        return {"evaluation": result}

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
