"""Analyzer node — evaluates a job against filter criteria using structured summary data.

Public interface:
    AnalyzerNode(BaseNode)  — class-based, injectable LLM client
    analyzer_node(state, llm_client)  — module-level shim for backwards compat
"""

import asyncio
import json
from loguru import logger
from typing import Any, Dict, List, Optional

from infra.llm_client import BaseLLMClient, LLMClientError, create_llm_client
from infra.models import JobEvaluation
from infra.json_repair import repair_json
from agent.state import AgentState
from agent.nodes.base import BaseNode
from agent.prompts.analyzer_prompt import ANALYZER_SYSTEM, build_analyzer_prompt
from utils.config import settings


# Fields evaluated by majority vote across the ensemble
BOOLEAN_FIELDS = [
    "keyword_match",
    "visa_sponsorship",
    "entry_level",
    "requires_phd",
    "is_internship",
]


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
        result["entry_level"] = None  # ambiguous — let LLM decide

    # keyword_match: requires semantic judgment, leave to LLM
    result["keyword_match"] = None

    return result


def _parse_text_fallback(response_text: str) -> Dict[str, Any]:
    """Parse LLM text response into evaluation dict (fallback for structured-mode failure).

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

    # Fallback: default to permissive so the job is not silently filtered out
    return {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": True,
        "requires_phd": False,
        "is_internship": False,
        "reason": "JSON parse error - defaulting to pass",
    }


def _build_analyzer_client() -> BaseLLMClient:
    """Construct the LLM client for Analyzer from settings."""
    return create_llm_client(
        provider=settings.analyzer_provider,
        model=settings.analyzer_model,
    )


def _majority_vote_evaluation(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a consensus evaluation dict by majority vote over boolean fields."""
    evaluation: Dict[str, Any] = {}
    total = len(results)
    for field in BOOLEAN_FIELDS:
        true_votes = sum(1 for r in results if bool(r.get(field, False)))
        evaluation[field] = true_votes > (total / 2)
    return evaluation


def _pick_closest_reason(results: List[Dict[str, Any]], evaluation: Dict[str, Any]) -> str:
    """Return the reason from the ensemble member whose votes best match the consensus."""
    def distance(result: Dict[str, Any]) -> int:
        return sum(
            bool(result.get(f, False)) != bool(evaluation.get(f, False))
            for f in BOOLEAN_FIELDS
        )

    best = min(results, key=distance)
    return best.get("reason", "")


class AnalyzerNode(BaseNode):
    """LangGraph node that evaluates a job against user-defined criteria.

    Uses liquid/lfm-2.2-6b via OpenRouter by default. Inject a different
    ``BaseLLMClient`` for testing or to switch providers at runtime.
    """

    def __init__(self, llm_client: Optional[BaseLLMClient] = None) -> None:
        """
        Args:
            llm_client: LLM provider to use. When None, reads ANALYZER_PROVIDER /
                        ANALYZER_MODEL env vars to build a default client.
        """
        super().__init__(llm_client or _build_analyzer_client())

    async def _call_llm_analyzer(
        self,
        summary: Dict[str, Any],
        search_terms: List[str],
        accumulated_feedback: List[str],
        job: Dict[str, Any],
        temperature: Optional[float] = 0.0,
    ) -> Dict[str, Any]:
        """Call the analyzer LLM once and return the evaluation dict."""
        job_context = self._job_context(job)
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
            evaluation_model = await self.llm_client.complete_structured(
                messages, JobEvaluation, job_context=job_context, temperature=temperature
            )
            return evaluation_model.model_dump()
        except LLMClientError:
            logger.warning(f"Structured output failed [{job_context}], falling back to text")
            response_text = await self.llm_client.complete_text(
                messages, job_context=job_context, temperature=temperature
            )
            return _parse_text_fallback(response_text)

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        """Evaluate job against filter criteria using an ensemble of LLM calls.

        Runs ``len(ANALYZER_TEMPERATURES)`` parallel analyzer calls, combines them
        by majority vote, then applies deterministic overrides for unambiguous fields.

        Args:
            state: Current agent state with 'job', 'summary', 'search_terms'.

        Returns:
            State updates: ``{'evaluation': dict}`` on success or ``{'error': str}``.
        """
        summary = state.get("summary")
        search_terms = state["search_terms"]
        accumulated_feedback = state.get("accumulated_feedback", [])
        job = state["job"]
        job_context = self._job_context(job)
        job_title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")

        if not summary:
            return {"error": "No summary available for analysis"}

        try:
            deterministic = _deterministic_eval(summary, search_terms)

            # Run all 3 ensemble members in parallel
            calls = [
                self._call_llm_analyzer(
                    summary, search_terms, accumulated_feedback, job
                )
                for _ in range(3)
            ]
            raw_results = await asyncio.gather(*calls, return_exceptions=True)

            analyzer_results: List[Dict[str, Any]] = []
            for item in raw_results:
                if isinstance(item, Exception):
                    logger.warning(f"Analyzer ensemble call failed [{job_context}]: {item}")
                    continue
                analyzer_results.append(item)

            if not analyzer_results:
                return {"error": f"All analyzer ensemble calls failed [{job_context}]"}

            evaluation = _majority_vote_evaluation(analyzer_results)

            # Deterministic rules override model votes when explicit signals are present
            for field, value in deterministic.items():
                if value is not None:
                    if evaluation.get(field) != value:
                        logger.debug(
                            f"Deterministic override [{job_context}]: "
                            f"{field} {evaluation.get(field)} -> {value}"
                        )
                    evaluation[field] = value

            evaluation["reason"] = _pick_closest_reason(analyzer_results, evaluation)
            evaluation["job_title"] = job_title
            evaluation["company"] = company

            logger.info(
                f"EVALUATED [{job_context}]: "
                f"keyword={evaluation.get('keyword_match')}, "
                f"visa={evaluation.get('visa_sponsorship')}, "
                f"entry={evaluation.get('entry_level')}, "
                f"phd={evaluation.get('requires_phd')}, "
                f"intern={evaluation.get('is_internship')}"
            )
            return {"evaluation": evaluation}

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
            logger.error(f"Analyzer unexpected error [{job_context}]: {e}")
            return {"error": str(e)}


async def analyzer_node(state: AgentState, llm_client: BaseLLMClient) -> Dict[str, Any]:
    """Module-level wrapper kept for backwards compatibility.

    Prefer instantiating ``AnalyzerNode`` directly.
    """
    return await AnalyzerNode(llm_client)(state)
