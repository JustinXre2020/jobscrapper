"""LangGraph workflow assembly.

Current topology:
    [START] -> [Summarizer] -> [AnalyzerEnsemble x3] -> [END]

Each node is backed by its own ``BaseLLMClient`` instance so that
Summarizer and Analyzer can use different models/providers.
"""

from loguru import logger
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph

from agent.nodes.analyzer import AnalyzerNode
from agent.nodes.summarizer import SummarizerNode
from agent.state import JobState
from infra.llm_client import BaseLLMClient


def route_after_summarize(state: JobState) -> str:
    """Route after Summarizer: skip to END if error/skipped, else run analyzer."""
    if state.get("skipped") or (state.get("error") and not state.get("summary")):
        return END
    return "analyzer"


def build_graph(
    summarizer_client: Optional[BaseLLMClient] = None,
    analyzer_client: Optional[BaseLLMClient] = None,
):
    """Build the per-job graph: Summarizer -> Analyzer -> END.

    Args:
        summarizer_client: LLM client for the Summarizer node. When None,
            SummarizerNode reads SUMMARIZER_PROVIDER / SUMMARIZER_MODEL env vars.
        analyzer_client: LLM client for the Analyzer node. When None,
            AnalyzerNode reads ANALYZER_PROVIDER / ANALYZER_MODEL env vars.
    """
    logger.info("Using single-job workflow (Summarizer -> 3x Analyzer)")

    graph = StateGraph(JobState)
    graph.add_node("summarizer", SummarizerNode(summarizer_client))
    graph.add_node("analyzer", AnalyzerNode(analyzer_client))

    graph.set_entry_point("summarizer")
    graph.add_conditional_edges("summarizer", route_after_summarize)
    graph.add_edge("analyzer", END)
    return graph.compile()


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
