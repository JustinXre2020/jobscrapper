"""Tests for the Reviewer node prompt.

Tests contradiction detection: feeds known summary + deliberately wrong evaluation,
verifies reviewer catches it. Also tests that consistent evaluations are approved.
Requires OPENROUTER_API_KEY.
"""

import json

import pytest

from agent.prompts.reviewer_prompt import REVIEWER_SYSTEM, build_reviewer_prompt
from infra.llm_client import LLMClient
from infra.models import ReviewResult
from infra.json_repair import repair_json


# --- Consistent case: should approve ---

CONSISTENT_SUMMARY = {
    "title_normalized": "Software Engineer",
    "role_type": "software_engineering",
    "seniority_level": "senior",
    "years_experience_required": 5,
    "education_required": "bachelors",
    "visa_statements": [],
    "is_internship_coop": False,
    "key_requirements": ["Python", "AWS", "5+ years"],
    "description_summary": "Senior backend engineer working on cloud services.",
}

CONSISTENT_EVALUATION = {
    "keyword_match": True,
    "visa_sponsorship": True,  # empty visa_statements -> True
    "entry_level": False,  # 5 years -> not entry
    "requires_phd": False,
    "is_internship": False,
    "reason": "Title matches target. No visa restrictions. 5 years experience = not entry.",
}


# --- Contradictory case: entry_level=True but 8 years + senior ---

CONTRADICTORY_SUMMARY = {
    "title_normalized": "Software Engineer",
    "role_type": "software_engineering",
    "seniority_level": "senior",
    "years_experience_required": 8,
    "education_required": "bachelors",
    "visa_statements": ["No visa sponsorship available"],
    "is_internship_coop": False,
    "key_requirements": ["8+ years C++", "RTOS"],
    "description_summary": "Senior embedded software engineer.",
}

CONTRADICTORY_EVALUATION = {
    "keyword_match": True,
    "visa_sponsorship": True,  # WRONG: visa_statements says no sponsorship
    "entry_level": True,  # WRONG: 8 years + senior
    "requires_phd": False,
    "is_internship": False,
    "reason": "Title matches. Visa looks fine. Entry level role.",
}


# --- Contradictory case: internship mismatch ---

INTERNSHIP_SUMMARY = {
    "title_normalized": "Data Analyst Intern",
    "role_type": "data_analysis",
    "seniority_level": "intern",
    "years_experience_required": None,
    "education_required": "bachelors",
    "visa_statements": [],
    "is_internship_coop": True,
    "key_requirements": ["Excel", "SQL"],
    "description_summary": "Summer internship for data analysis.",
}

INTERNSHIP_WRONG_EVAL = {
    "keyword_match": True,
    "visa_sponsorship": True,
    "entry_level": True,
    "requires_phd": False,
    "is_internship": False,  # WRONG: summary says is_internship_coop=True
    "reason": "Title matches. No visa restriction. Entry level internship.",
}


async def _call_reviewer(
    llm_client: LLMClient, summary: dict, evaluation: dict, search_terms: list[str]
) -> dict:
    """Call the reviewer prompt and return parsed dict."""
    prompt = build_reviewer_prompt(summary, evaluation, search_terms)
    messages = [
        {"role": "system", "content": REVIEWER_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    try:
        model = await llm_client.complete_structured(messages, ReviewResult)
        return model.model_dump()
    except Exception:
        text = await llm_client.complete_text(messages)
        repaired = repair_json(text)
        raw = json.loads(repaired)
        model = ReviewResult.model_validate(raw)
        return model.model_dump()


@pytest.mark.live
class TestReviewerApproval:
    """Verify reviewer approves logically consistent evaluations."""

    @pytest.mark.asyncio
    async def test_approves_consistent_evaluation(
        self, llm_client: LLMClient
    ) -> None:
        result = await _call_reviewer(
            llm_client,
            CONSISTENT_SUMMARY,
            CONSISTENT_EVALUATION,
            ["software engineer"],
        )
        assert result["approved"] is True, (
            f"Expected approved=True for consistent evaluation, "
            f"got feedback: {result.get('feedback')}"
        )


@pytest.mark.live
class TestReviewerContradictionDetection:
    """Verify reviewer catches obvious contradictions."""

    @pytest.mark.asyncio
    async def test_catches_entry_level_contradiction(
        self, llm_client: LLMClient
    ) -> None:
        """entry_level=True with 8 years + senior seniority is a clear contradiction."""
        result = await _call_reviewer(
            llm_client,
            CONTRADICTORY_SUMMARY,
            CONTRADICTORY_EVALUATION,
            ["software engineer"],
        )
        assert result["approved"] is False, (
            f"Expected approved=False for entry_level contradiction, "
            f"got feedback: {result.get('feedback')}"
        )

    @pytest.mark.asyncio
    async def test_catches_visa_contradiction(
        self, llm_client: LLMClient
    ) -> None:
        """visa_sponsorship=True with explicit 'No visa sponsorship' is a contradiction."""
        result = await _call_reviewer(
            llm_client,
            CONTRADICTORY_SUMMARY,
            CONTRADICTORY_EVALUATION,
            ["software engineer"],
        )
        # The evaluation has two errors; reviewer should catch at least one
        assert result["approved"] is False

    @pytest.mark.asyncio
    async def test_catches_internship_mismatch(
        self, llm_client: LLMClient
    ) -> None:
        """is_internship=False when summary says is_internship_coop=True is a contradiction."""
        result = await _call_reviewer(
            llm_client,
            INTERNSHIP_SUMMARY,
            INTERNSHIP_WRONG_EVAL,
            ["data analyst"],
        )
        assert result["approved"] is False, (
            f"Expected approved=False for internship mismatch, "
            f"got feedback: {result.get('feedback')}"
        )
