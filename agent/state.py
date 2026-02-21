"""Agent state definitions for the LangGraph workflow."""

from typing import Any, Dict, List, Optional, TypedDict


class JobState(TypedDict):
    """State passed between nodes in the per-job graph."""

    job: Dict[str, Any]
    search_terms: List[str]
    summary: Optional[Dict[str, Any]]
    evaluation: Optional[Dict[str, Any]]
    accumulated_feedback: List[str]
    error: Optional[str]
    skipped: bool


# Backwards compatibility alias
AgentState = JobState
