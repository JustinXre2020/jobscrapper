"""Tests for the Summarizer node prompt.

Tests schema compliance and field accuracy across LLM models.
Requires OPENROUTER_API_KEY to run (marked with @pytest.mark.live).
"""

import json

import pytest

from agent.prompts import SUMMARIZER_SYSTEM, build_summarizer_prompt
from infra.llm_client import LLMClient
from infra.models import JobSummaryModel
from infra.json_repair import repair_json
from tests.fixtures.jobs import JobFixture

# Valid enum values for validation
VALID_ROLE_TYPES = {
    "software_engineering", "data_science", "data_engineering", "data_analysis",
    "product_management", "project_management", "design", "devops", "security",
    "qa", "other",
}
VALID_SENIORITY_LEVELS = {
    "intern", "entry", "mid", "senior", "lead", "staff", "principal",
    "director", "vp", "unknown",
}
VALID_EDUCATION_LEVELS = {
    "none", "high_school", "bachelors", "masters", "phd", "unknown",
}


async def _call_summarizer(llm_client: LLMClient, fixture: JobFixture) -> dict:
    """Call the summarizer prompt and return parsed dict (with JSON repair fallback)."""
    prompt = build_summarizer_prompt(fixture["job"], fixture["search_terms"])
    messages = [
        {"role": "system", "content": SUMMARIZER_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    try:
        model = await llm_client.complete_structured(messages, JobSummaryModel)
        return model.model_dump()
    except Exception:
        # Fall back to text + repair (mirrors production behavior)
        text = await llm_client.complete_text(messages)
        repaired = repair_json(text)
        raw = json.loads(repaired)
        model = JobSummaryModel.model_validate(raw)
        return model.model_dump()


@pytest.mark.live
class TestSchemaCompliance:
    """Verify the LLM response parses into a valid JobSummaryModel."""

    @pytest.mark.asyncio
    async def test_parses_to_model(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """Response must parse into JobSummaryModel without errors."""
        result = await _call_summarizer(llm_client, job_fixture)
        assert isinstance(result, dict)
        assert "title_normalized" in result
        assert "role_type" in result
        assert "seniority_level" in result

    @pytest.mark.asyncio
    async def test_role_type_valid(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """role_type must be one of the allowed enum values."""
        result = await _call_summarizer(llm_client, job_fixture)
        assert result["role_type"] in VALID_ROLE_TYPES, (
            f"Invalid role_type: {result['role_type']}"
        )

    @pytest.mark.asyncio
    async def test_seniority_level_valid(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """seniority_level must be one of the allowed enum values."""
        result = await _call_summarizer(llm_client, job_fixture)
        assert result["seniority_level"] in VALID_SENIORITY_LEVELS, (
            f"Invalid seniority_level: {result['seniority_level']}"
        )

    @pytest.mark.asyncio
    async def test_education_required_valid(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """education_required must be one of the allowed enum values."""
        result = await _call_summarizer(llm_client, job_fixture)
        assert result["education_required"] in VALID_EDUCATION_LEVELS, (
            f"Invalid education_required: {result['education_required']}"
        )

    @pytest.mark.asyncio
    async def test_key_requirements_is_list(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """key_requirements must be a list."""
        result = await _call_summarizer(llm_client, job_fixture)
        assert isinstance(result["key_requirements"], list)

    @pytest.mark.asyncio
    async def test_visa_statements_is_list(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """visa_statements must be a list."""
        result = await _call_summarizer(llm_client, job_fixture)
        assert isinstance(result["visa_statements"], list)


@pytest.mark.live
class TestFieldAccuracy:
    """Verify extracted fields match expected values for each fixture."""

    @pytest.mark.asyncio
    async def test_seniority_level(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """seniority_level should match expected value."""
        expected = job_fixture["expected_summary"].get("seniority_level")
        if expected is None:
            pytest.skip("No expected seniority_level for this fixture")
        result = await _call_summarizer(llm_client, job_fixture)
        assert result["seniority_level"] == expected, (
            f"Expected seniority={expected}, got {result['seniority_level']}"
        )

    @pytest.mark.asyncio
    async def test_years_experience(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """years_experience_required should match expected value."""
        expected = job_fixture["expected_summary"].get("years_experience_required")
        if "years_experience_required" not in job_fixture["expected_summary"]:
            pytest.skip("No expected years_experience for this fixture")
        result = await _call_summarizer(llm_client, job_fixture)
        assert result["years_experience_required"] == expected, (
            f"Expected years={expected}, got {result['years_experience_required']}"
        )

    @pytest.mark.asyncio
    async def test_is_internship(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """is_internship_coop should match expected value."""
        expected = job_fixture["expected_summary"].get("is_internship_coop")
        if expected is None:
            pytest.skip("No expected is_internship_coop for this fixture")
        result = await _call_summarizer(llm_client, job_fixture)
        assert result["is_internship_coop"] == expected, (
            f"Expected internship={expected}, got {result['is_internship_coop']}"
        )

    @pytest.mark.asyncio
    async def test_role_type(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """role_type should match expected value."""
        expected = job_fixture["expected_summary"].get("role_type")
        if expected is None:
            pytest.skip("No expected role_type for this fixture")
        result = await _call_summarizer(llm_client, job_fixture)
        assert result["role_type"] == expected, (
            f"Expected role_type={expected}, got {result['role_type']}"
        )

    @pytest.mark.asyncio
    async def test_visa_statements_populated(
        self, llm_client: LLMClient, job_fixture: JobFixture
    ) -> None:
        """visa_statements should be non-empty when visa language exists."""
        expected_nonempty = job_fixture["expected_summary"].get("visa_statements_nonempty")
        if expected_nonempty is None:
            pytest.skip("No visa expectation for this fixture")
        result = await _call_summarizer(llm_client, job_fixture)
        has_statements = len(result.get("visa_statements", [])) > 0
        assert has_statements == expected_nonempty, (
            f"Expected visa_statements non-empty={expected_nonempty}, "
            f"got {result.get('visa_statements', [])}"
        )
