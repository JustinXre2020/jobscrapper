"""LangGraph workflow assembly.

Graph topology:
    [START] -> [Summarizer] -> [Analyzer] -----------------> [Reviewer]
                                   ^                              |
                                   |      (rejected + retries)    |
                                   +------------------------------+
                                   |
                          (not sampled / approved / max retries)
                                   v
                                [END]
"""

import os
import logging
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph, END

from infra.llm_client import LLMClient
from agent.state import AgentState
from agent.nodes.summarizer import summarizer_node
from agent.nodes.analyzer import analyzer_node
from agent.nodes.reviewer import reviewer_node

logger = logging.getLogger(__name__)

REVIEWER_SAMPLE_RATE = float(os.getenv("REVIEWER_SAMPLE_RATE", "0.2"))


def _wrap_summarizer(llm_client: LLMClient):
    """Create a summarizer node function bound to a specific LLMClient."""
    async def _node(state: AgentState) -> Dict[str, Any]:
        return await summarizer_node(state, llm_client)
    return _node


def _wrap_analyzer(llm_client: LLMClient):
    """Create an analyzer node function bound to a specific LLMClient."""
    async def _node(state: AgentState) -> Dict[str, Any]:
        return await analyzer_node(state, llm_client)
    return _node


def _wrap_reviewer(llm_client: LLMClient):
    """Create a reviewer node function bound to a specific LLMClient."""
    async def _node(state: AgentState) -> Dict[str, Any]:
        return await reviewer_node(state, llm_client)
    return _node


def route_after_summarize(state: AgentState) -> str:
    """Route after Summarizer: skip to END if error/skipped, else go to Analyzer."""
    if state.get("skipped") or (state.get("error") and not state.get("summary")):
        return END
    return "analyzer"


def route_after_analyze(state: AgentState) -> str:
    """Route after Analyzer: review or skip to END.

    Jobs with errors always skip review.
    """
    if state.get("error") and not state.get("evaluation"):
        return END

    return "reviewer"


def route_after_review(state: AgentState) -> str:
    """Route after Reviewer: retry Analyzer if rejected and retries remain, else END."""
    if state.get("review_passed", True):
        return END

    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 1)

    if retry_count < max_retries:
        logger.info(
            f"Reviewer rejected, retrying analyzer "
            f"(retry {retry_count + 1}/{max_retries})"
        )
        return "analyzer"

    logger.info("Reviewer rejected but max retries reached, proceeding to END")
    return END


def build_graph(llm_client: LLMClient) -> StateGraph:
    """Construct the 3-node LangGraph workflow.

    Args:
        llm_client: Provider-agnostic LLM client shared across nodes.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    graph = StateGraph(AgentState)

    # Add nodes with bound LLM client
    graph.add_node("summarizer", _wrap_summarizer(llm_client))
    graph.add_node("analyzer", _wrap_analyzer(llm_client))
    graph.add_node("reviewer", _wrap_reviewer(llm_client))

    # Set entry point
    graph.set_entry_point("summarizer")

    # Conditional edges
    graph.add_conditional_edges("summarizer", route_after_summarize)
    graph.add_conditional_edges("analyzer", route_after_analyze)
    graph.add_conditional_edges("reviewer", route_after_review)

    return graph.compile()


async def run_single_job(
    compiled_graph: Any,
    job: Dict[str, Any],
    search_terms: List[str],
    accumulated_feedback: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run a single job through the agent workflow.

    Args:
        compiled_graph: Compiled LangGraph.
        job: Raw job dict from scraper.
        search_terms: Target roles to match.
        accumulated_feedback: Historic reviewer corrections.

    Returns:
        Final agent state after workflow completes.
    """
    initial_state: AgentState = {
        "job": job,
        "search_terms": search_terms,
        "summary": None,
        "evaluation": None,
        "review_passed": None,
        "review_feedback": None,
        "retry_count": 0,
        "max_retries": 1,
        "accumulated_feedback": accumulated_feedback or [],
        "error": None,
        "skipped": False,
    }

    result = await compiled_graph.ainvoke(initial_state)
    return result
