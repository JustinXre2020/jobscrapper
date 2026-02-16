"""Agent state definition for the LangGraph workflow."""

from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict):
    """State passed between nodes in the LangGraph workflow."""

    job: Dict[str, Any]
    search_terms: List[str]
    summary: Optional[Dict[str, Any]]
    evaluation: Optional[Dict[str, Any]]
    review_passed: Optional[bool]
    review_feedback: Optional[str]
    retry_count: int
    max_retries: int
    accumulated_feedback: List[str]
    error: Optional[str]
    skipped: bool
