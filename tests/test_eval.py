"""Evaluation test suite — measures per-field and end-to-end agent accuracy.

Requires OPENROUTER_API_KEY. Run with:
    pytest tests/test_eval.py -v
"""

import json
from collections import defaultdict

import pytest

from agent.nodes.analyzer import _deterministic_eval
from agent.prompts.analyzer_prompt import ANALYZER_SYSTEM, build_analyzer_prompt
from infra.llm_client import LLMClient
from infra.models import JobEvaluation
from infra.json_repair import repair_json
from tests.fixtures.eval_jobs import EVAL_FIXTURES, EVAL_IDS, EvalFixture

EVAL_FIELDS = [
    "keyword_match",
    "visa_sponsorship",
    "entry_level",
    "is_internship",
    "requires_phd",
]

ACCURACY_THRESHOLD = 0.80  # 80% minimum per-field accuracy


async def _run_analyzer(
    llm_client: LLMClient, fixture: EvalFixture
) -> dict:
    """Run the analyzer (deterministic + LLM) on a single eval fixture."""
    summary = fixture["summary"]
    search_terms = fixture["search_terms"]

    # Deterministic pre-check
    deterministic = _deterministic_eval(summary, search_terms)

    # LLM evaluation
    prompt = build_analyzer_prompt(summary, search_terms)
    messages = [
        {"role": "system", "content": ANALYZER_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    try:
        model = await llm_client.complete_structured(messages, JobEvaluation)
        result = model.model_dump()
    except Exception:
        text = await llm_client.complete_text(messages)
        repaired = repair_json(text)
        raw = json.loads(repaired)
        result = JobEvaluation.model_validate(raw).model_dump()

    # Apply deterministic overrides
    for field, value in deterministic.items():
        if value is not None:
            result[field] = value

    return result


class TestDeterministicEval:
    """Test the deterministic pre-check function in isolation (no LLM needed)."""

    @pytest.mark.parametrize(
        "fixture", EVAL_FIXTURES, ids=EVAL_IDS
    )
    def test_deterministic_fields(self, fixture: EvalFixture) -> None:
        """Verify deterministic results match expected values where not None."""
        result = _deterministic_eval(fixture["summary"], fixture["search_terms"])
        expected = fixture["expected"]

        for field in EVAL_FIELDS:
            det_value = result.get(field)
            if det_value is not None and field in expected:
                assert det_value == expected[field], (
                    f"[{fixture['id']}] deterministic {field}: "
                    f"got {det_value}, expected {expected[field]}"
                )


@pytest.mark.live
class TestAnalyzerEvalAccuracy:
    """Run full analyzer (deterministic + LLM) on eval dataset and measure accuracy."""

    @pytest.fixture(params=list(range(len(EVAL_FIXTURES))), ids=EVAL_IDS)
    def eval_index(self, request: pytest.FixtureRequest) -> int:
        return request.param

    @pytest.mark.asyncio
    async def test_field_accuracy(
        self, llm_client: LLMClient, eval_index: int
    ) -> None:
        """Per-fixture accuracy: all fields must match expected."""
        fixture = EVAL_FIXTURES[eval_index]
        result = await _run_analyzer(llm_client, fixture)
        expected = fixture["expected"]

        mismatches = []
        for field in EVAL_FIELDS:
            if field in expected and result.get(field) != expected[field]:
                mismatches.append(
                    f"{field}: got {result.get(field)}, expected {expected[field]}"
                )

        assert not mismatches, (
            f"[{fixture['id']}] mismatches: {'; '.join(mismatches)}"
        )
