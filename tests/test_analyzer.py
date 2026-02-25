"""Tests for the Analyzer node prompt.

Feeds known-correct summary dicts (bypassing summarizer) to isolate
analyzer evaluation accuracy. Requires OPENROUTER_API_KEY.
"""

import json

import pytest

from agent.prompts import ANALYZER_SYSTEM, build_analyzer_prompt
from infra.llm_client import LLMClient
from infra.models import JobEvaluation
from infra.json_repair import repair_json
from tests.fixtures.jobs import ALL_FIXTURES, FIXTURE_IDS

# Pre-built "perfect" summaries that match each fixture's expected_summary.
# This isolates the analyzer from summarizer errors.
PERFECT_SUMMARIES = [
    {
        "title_normalized": "Embedded Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "senior",
        "years_experience_required": 8,
        "education_required": "bachelors",
        "visa_statements": [
            "US Citizenship is required",
            "No visa sponsorship available",
        ],
        "is_internship_coop": False,
        "key_requirements": [
            "8+ years embedded C/C++",
            "RTOS experience",
            "DO-178C",
            "hardware/software integration",
        ],
        "description_summary": "Senior embedded software engineer for defense real-time systems.",
    },
    {
        "title_normalized": "SAP Intern",
        "role_type": "other",
        "seniority_level": "intern",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [
            "Must be legally authorized to work in the United States without the need for employer sponsorship",
        ],
        "is_internship_coop": True,
        "key_requirements": [
            "Pursuing Bachelor's or Master's in IS or CS",
            "Interest in enterprise technology",
        ],
        "description_summary": "Summer internship supporting SAP S/4HANA implementation projects.",
    },
    {
        "title_normalized": "DevOps Engineer",
        "role_type": "devops",
        "seniority_level": "mid",
        "years_experience_required": 3,
        "education_required": "bachelors",
        "visa_statements": [
            "Candidates must be a U.S. Person",
        ],
        "is_internship_coop": False,
        "key_requirements": [
            "3+ years CI/CD",
            "Python",
            "Docker",
            "Kubernetes",
            "AWS or Azure",
        ],
        "description_summary": "DevOps engineer supporting R&D infrastructure with CI/CD and cloud.",
    },
    {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "entry",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": [
            "JavaScript/TypeScript",
            "REST APIs",
            "databases",
        ],
        "description_summary": "Junior web developer role using React and Node.js at a startup.",
    },
]


async def _call_analyzer(
    llm_client: LLMClient, summary: dict, search_terms: list[str]
) -> dict:
    """Call the analyzer prompt and return parsed dict."""
    prompt = build_analyzer_prompt(summary, search_terms)
    messages = [
        {"role": "system", "content": ANALYZER_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    try:
        model = await llm_client.complete_structured(messages, JobEvaluation)
        return model.model_dump()
    except Exception:
        text = await llm_client.complete_text(messages)
        repaired = repair_json(text)
        raw = json.loads(repaired)
        model = JobEvaluation.model_validate(raw)
        return model.model_dump()


@pytest.mark.live
class TestAnalyzerAccuracy:
    """Feed perfect summaries and verify evaluation field accuracy."""

    @pytest.fixture(params=list(range(len(ALL_FIXTURES))), ids=FIXTURE_IDS)
    def fixture_index(self, request: pytest.FixtureRequest) -> int:
        return request.param

    @pytest.mark.asyncio
    async def test_keyword_match(
        self, llm_client: LLMClient, fixture_index: int
    ) -> None:
        fixture = ALL_FIXTURES[fixture_index]
        summary = PERFECT_SUMMARIES[fixture_index]
        expected = fixture["expected_evaluation"].get("keyword_match")
        if expected is None:
            pytest.skip("No expected keyword_match")
        result = await _call_analyzer(llm_client, summary, fixture["search_terms"])
        assert result["keyword_match"] == expected, (
            f"Expected keyword_match={expected}, got {result['keyword_match']}"
        )

    @pytest.mark.asyncio
    async def test_visa_sponsorship(
        self, llm_client: LLMClient, fixture_index: int
    ) -> None:
        fixture = ALL_FIXTURES[fixture_index]
        summary = PERFECT_SUMMARIES[fixture_index]
        expected = fixture["expected_evaluation"].get("visa_sponsorship")
        if expected is None:
            pytest.skip("No expected visa_sponsorship")
        result = await _call_analyzer(llm_client, summary, fixture["search_terms"])
        assert result["visa_sponsorship"] == expected, (
            f"Expected visa_sponsorship={expected}, got {result['visa_sponsorship']}"
        )

    @pytest.mark.asyncio
    async def test_job_level(
        self, llm_client: LLMClient, fixture_index: int
    ) -> None:
        fixture = ALL_FIXTURES[fixture_index]
        summary = PERFECT_SUMMARIES[fixture_index]
        expected = fixture["expected_evaluation"].get("job_level")
        if expected is None:
            pytest.skip("No expected job_level")
        result = await _call_analyzer(llm_client, summary, fixture["search_terms"])
        assert result["job_level"] == expected, (
            f"Expected job_level={expected!r}, got {result['job_level']!r}"
        )

    @pytest.mark.asyncio
    async def test_requires_phd(
        self, llm_client: LLMClient, fixture_index: int
    ) -> None:
        fixture = ALL_FIXTURES[fixture_index]
        summary = PERFECT_SUMMARIES[fixture_index]
        expected = fixture["expected_evaluation"].get("requires_phd")
        if expected is None:
            pytest.skip("No expected requires_phd")
        result = await _call_analyzer(llm_client, summary, fixture["search_terms"])
        assert result["requires_phd"] == expected, (
            f"Expected requires_phd={expected}, got {result['requires_phd']}"
        )
