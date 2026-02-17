#!/usr/bin/env python3
"""Standalone eval runner — prints per-field accuracy table.

Usage:
    python tests/eval_report.py
    TEST_MODELS="qwen/qwen3-30b-a3b:free" python tests/eval_report.py
"""

import asyncio
import json
import os
import sys
from collections import defaultdict

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.nodes.analyzer import _deterministic_eval
from agent.prompts.analyzer_prompt import ANALYZER_SYSTEM, build_analyzer_prompt
from infra.llm_client import LLMClient
from infra.models import JobEvaluation
from infra.json_repair import repair_json
from tests.fixtures.eval_jobs import EVAL_FIXTURES

EVAL_FIELDS = [
    "keyword_match",
    "visa_sponsorship",
    "entry_level",
    "is_internship",
    "requires_phd",
]


async def run_single(llm_client: LLMClient, fixture: dict) -> dict:
    """Run analyzer on a single fixture, return result dict."""
    summary = fixture["summary"]
    search_terms = fixture["search_terms"]

    deterministic = _deterministic_eval(summary, search_terms)

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

    for field, value in deterministic.items():
        if value is not None:
            result[field] = value

    return result


async def run_eval(model_name: str) -> None:
    """Run all eval fixtures and print accuracy report."""
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    client = LLMClient(model=model_name, api_key=api_key)
    print(f"Model: {model_name}")
    print(f"Fixtures: {len(EVAL_FIXTURES)}")
    print("-" * 50)

    field_correct = defaultdict(int)
    field_total = defaultdict(int)
    e2e_correct = 0
    errors = []

    for fixture in EVAL_FIXTURES:
        fid = fixture["id"]
        expected = fixture["expected"]

        try:
            result = await run_single(client, fixture)
        except Exception as e:
            print(f"  ERROR [{fid}]: {e}")
            errors.append(fid)
            continue

        all_match = True
        for field in EVAL_FIELDS:
            if field in expected:
                field_total[field] += 1
                if result.get(field) == expected[field]:
                    field_correct[field] += 1
                else:
                    all_match = False
                    print(
                        f"  MISS [{fid}] {field}: "
                        f"got={result.get(field)}, expected={expected[field]}"
                    )

        if all_match:
            e2e_correct += 1

    # Report
    print()
    print("=" * 50)
    print("Field Accuracy:")
    total_correct = 0
    total_fields = 0
    for field in EVAL_FIELDS:
        c = field_correct[field]
        t = field_total[field]
        total_correct += c
        total_fields += t
        pct = (c / t * 100) if t else 0
        bar = "PASS" if pct >= 80 else "FAIL"
        print(f"  {field:20s}: {c:2d}/{t:2d} ({pct:5.1f}%) [{bar}]")

    overall = (total_correct / total_fields * 100) if total_fields else 0
    print(f"\nOverall: {total_correct}/{total_fields} ({overall:.1f}%)")

    n = len(EVAL_FIXTURES) - len(errors)
    e2e_pct = (e2e_correct / n * 100) if n else 0
    print(f"End-to-end pass/fail: {e2e_correct}/{n} ({e2e_pct:.1f}%)")

    if errors:
        print(f"\nErrors ({len(errors)}): {', '.join(errors)}")


def main():
    env_models = os.getenv("TEST_MODELS", "")
    if env_models.strip():
        models = [m.strip() for m in env_models.split(",") if m.strip()]
    else:
        models = ["qwen/qwen3-30b-a3b:free"]

    for model in models:
        asyncio.run(run_eval(model))
        print()


if __name__ == "__main__":
    main()
