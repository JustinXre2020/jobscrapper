"""LangGraph workflow assembly.

Current topology:
    [START] -> [Summarizer] -> [AnalyzerEnsemble x3] -> [END]

Each node is backed by its own ``BaseLLMClient`` instance so that
Summarizer and Analyzer can use different models/providers.
"""

import asyncio
from loguru import logger
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph

from agent.nodes.analyzer import AnalyzerNode, _deterministic_eval
from agent.nodes.summarizer import SummarizerNode
from agent.state import AgentState, JobState
from infra.llm_client import BaseLLMClient


BOOLEAN_FIELDS = [
    "keyword_match",
    "visa_sponsorship",
    "entry_level",
    "requires_phd",
    "is_internship",
]
ANALYZER_TEMPERATURES = [0.0, 0.0, 0.0]


def _wrap_summarizer(summarizer_node: SummarizerNode):
    async def _node(state: AgentState) -> Dict[str, Any]:
        return await summarizer_node(state)

    return _node


def _majority_vote_evaluation(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    evaluation: Dict[str, Any] = {}
    total = len(results)

    for field in BOOLEAN_FIELDS:
        true_votes = sum(1 for result in results if bool(result.get(field, False)))
        evaluation[field] = true_votes > (total / 2)

    return evaluation


def _pick_closest_reason(results: List[Dict[str, Any]], evaluation: Dict[str, Any]) -> str:
    def distance(result: Dict[str, Any]) -> int:
        return sum(
            bool(result.get(field, False)) != bool(evaluation.get(field, False))
            for field in BOOLEAN_FIELDS
        )

    best = min(results, key=distance)
    return best.get("reason", "")


def _wrap_analyzer_ensemble(analyzer_node: AnalyzerNode):
    async def _node(state: AgentState) -> Dict[str, Any]:
        summary = state.get("summary")
        if not summary:
            return {"error": "No summary available for analysis"}

        search_terms = state["search_terms"]
        accumulated_feedback = state.get("accumulated_feedback", [])
        job = state["job"]
        job_title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")
        job_context = f"{job_title} @ {company}"

        deterministic = _deterministic_eval(summary, search_terms)

        async def _run_once(temperature: float) -> Dict[str, Any]:
            # Each ensemble call uses the same AnalyzerNode client but a different temperature
            return await analyzer_node._call_llm_analyzer(
                summary,
                search_terms,
                accumulated_feedback,
                job,
                temperature=temperature,
            )

        calls = [_run_once(temp) for temp in ANALYZER_TEMPERATURES]
        raw_results = await asyncio.gather(*calls, return_exceptions=True)

        analyzer_results: List[Dict[str, Any]] = []
        for item in raw_results:
            if isinstance(item, Exception):
                logger.warning(f"Analyzer call failed [{job_context}]: {item}")
                continue
            analyzer_results.append(item)

        # Fail fast when every parallel analyzer call fails.
        if not analyzer_results:
            return {"error": f"All analyzer calls failed [{job_context}]"}

        evaluation = _majority_vote_evaluation(analyzer_results)

        # Deterministic rules override model votes when explicit signals are present.
        for field, value in deterministic.items():
            if value is not None:
                evaluation[field] = value

        # Keep a human-readable reason from the nearest analyzer output.
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

    return _node


def route_after_summarize(state: JobState) -> str:
    """Route after Summarizer: skip to END if error/skipped, else run analyzer ensemble."""
    if state.get("skipped") or (state.get("error") and not state.get("summary")):
        return END
    return "analyzer_ensemble"


def build_job_graph(
    summarizer_client: Optional[BaseLLMClient] = None,
    analyzer_client: Optional[BaseLLMClient] = None,
):
    """Build the per-job graph: Summarizer -> AnalyzerEnsemble -> END.

    Args:
        summarizer_client: LLM client for the Summarizer node. When None,
            SummarizerNode reads SUMMARIZER_PROVIDER / SUMMARIZER_MODEL env vars.
        analyzer_client: LLM client for the Analyzer node. When None,
            AnalyzerNode reads ANALYZER_PROVIDER / ANALYZER_MODEL env vars.
    """
    summarizer = SummarizerNode(summarizer_client)
    analyzer = AnalyzerNode(analyzer_client)

    graph = StateGraph(JobState)
    graph.add_node("summarizer", _wrap_summarizer(summarizer))
    graph.add_node("analyzer_ensemble", _wrap_analyzer_ensemble(analyzer))

    graph.set_entry_point("summarizer")
    graph.add_conditional_edges("summarizer", route_after_summarize)
    graph.add_edge("analyzer_ensemble", END)
    return graph.compile()


def build_graph(
    summarizer_client: Optional[BaseLLMClient] = None,
    analyzer_client: Optional[BaseLLMClient] = None,
):
    """Build the single-job graph.

    Args:
        summarizer_client: LLM client for Summarizer (or None to use env defaults).
        analyzer_client: LLM client for Analyzer (or None to use env defaults).
    """
    logger.info("Using single-job workflow (Summarizer -> 3x Analyzer ensemble)")
    return build_job_graph(summarizer_client, analyzer_client)


async def run_single_job(
    compiled_graph: Any,
    job: Dict[str, Any],
    search_terms: List[str],
    accumulated_feedback: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run a single job through the agent workflow."""
    initial_state: JobState = {
        "job": job,
        "search_terms": search_terms,
        "summary": None,
        "evaluation": None,
        "accumulated_feedback": accumulated_feedback or [],
        "error": None,
        "skipped": False,
    }

    return await compiled_graph.ainvoke(initial_state)
