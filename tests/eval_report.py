#!/usr/bin/env python3
"""Standalone eval runner — runs full pipeline on real jobs and prints classification report.

Loads 60 jobs from data/evaluated_jobs.json, runs each through
the LangGraph workflow, and reports precision/recall/accuracy/F1 per field.

Usage:
    python tests/eval_report.py
    TEST_MODELS="qwen/qwen3-30b-a3b:free" python tests/eval_report.py
"""

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger
from langgraph.graph.state import CompiledStateGraph

# Ensure src/ is on the path so project modules are importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)

from agent import build_graph, run_single_job
from infra.llm_client import create_llm_client
from utils.config import settings

_SUMMARIZER_PROVIDER = settings.summarizer_provider
_SUMMARIZER_MODEL = settings.summarizer_model

_ANALYZER_PROVIDER = settings.analyzer_provider
_ANALYZER_MODEL = settings.analyzer_model

EVAL_FIELDS = [
    "keyword_match",
    "visa_sponsorship",
    "job_level",
    "requires_phd",
]

DATA_PATH = Path(__file__).parent.parent / "data" / "evaluated_jobs.json"
ALL_SEARCH_TERMS = ["software engineer", "data analyst", "data engineer", "product manager"]
CONCURRENCY = settings.agent_concurrency


def _load_eval_data() -> List[Dict[str, Any]]:
    """Load evaluated jobs, separate job data from ground truth."""
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    results = []
    for job in data["jobs"]:
        job_copy = deepcopy(job)
        ground_truth = job_copy.pop("evaluation", {})
        results.append({"job": job_copy, "ground_truth": ground_truth})
    return results


async def _process_single_job(
    compiled_graph: Any,
    job: Dict[str, Any],
    search_terms: List[str],
    accumulated_feedback: List[str],
) -> Dict[str, Any]:
    """Run one job through LangGraph, matching filtering.job_filter behavior."""
    job_title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")

    try:
        final_state = await run_single_job(
            compiled_graph,
            job,
            search_terms,
            accumulated_feedback=accumulated_feedback,
        )

        if final_state.get("skipped"):
            return {
                "keyword_match": False,
                "visa_sponsorship": False,
                "job_level": "entry",
                "requires_phd": False,
                "reason": "No description available - skipped",
                "skipped": True,
                "job_title": job_title,
                "company": company,
            }

        if final_state.get("error") and not final_state.get("evaluation"):
            error_msg = final_state["error"]
            if "429" in error_msg or "Rate limited" in error_msg:
                return {
                    "keyword_match": False,
                    "visa_sponsorship": False,
                    "job_level": "senior",
                    "requires_phd": True,
                    "reason": "Rate limited (429) - filtered out",
                    "error": True,
                    "rate_limited": True,
                    "job_title": job_title,
                    "company": company,
                }
            return {
                "keyword_match": True,
                "visa_sponsorship": True,
                "job_level": "entry",
                "requires_phd": False,
                "reason": f"API error: {error_msg[:50]}",
                "error": True,
                "job_title": job_title,
                "company": company,
            }

        evaluation = final_state.get("evaluation", {})
        evaluation["job_title"] = job_title
        evaluation["company"] = company
        return evaluation

    except Exception as e:
        logger.error(f"Unexpected error processing {job_title} @ {company}: {e}")
        return {
            "keyword_match": True,
            "visa_sponsorship": True,
            "job_level": "entry",
            "requires_phd": False,
            "reason": f"Error: {str(e)[:50]}",
            "error": True,
            "job_title": job_title,
            "company": company,
        }


async def _run_all(
    eval_data: List[Dict[str, Any]],
    compiled_graph: CompiledStateGraph,
) -> List[Dict[str, Any]]:
    """Run all jobs via LangGraph in concurrent batches."""
    total = len(eval_data)
    completed = 0
    results: List[Dict[str, Any]] = []

    for batch_idx in range(0, total, CONCURRENCY):
        batch = eval_data[batch_idx : batch_idx + CONCURRENCY]

        predictions = await asyncio.gather(
            *[
                _process_single_job(
                    compiled_graph,
                    item["job"],
                    item["job"].get("search_terms", "")[0],
                    [],  # feedback 留空
                )
                for item in batch
            ]
        )

        for item, prediction in zip(batch, predictions):
            job = item["job"]
            title = job.get("title", "")
            completed += 1
            status = "ERROR" if prediction.get("error") else "OK"
            print(f"  [{completed}/{total}] {status} — {title}")
            results.append(
                {
                    "job_title": title,
                    "ground_truth": item["ground_truth"],
                    "prediction": prediction,
                }
            )

    return results


async def run_eval() -> None:
    """Run full evaluation and print report."""
    eval_data = _load_eval_data()
    summarizer_client = create_llm_client(
        provider=_SUMMARIZER_PROVIDER, model=_SUMMARIZER_MODEL
    )
    analyzer_client = create_llm_client(
        provider=_ANALYZER_PROVIDER, model=_ANALYZER_MODEL
    )
    compiled_graph = build_graph(summarizer_client, analyzer_client)

    print(f"Jobs: {len(eval_data)}")
    print("-" * 60)

    results = await _run_all(eval_data, compiled_graph)

    # Separate successful from errored
    errors = [r for r in results if r["prediction"].get("error")]
    valid = [r for r in results if not r["prediction"].get("error")]

    # Collect per-field labels
    field_true: Dict[str, List[int]] = {f: [] for f in EVAL_FIELDS}
    field_pred: Dict[str, List[int]] = {f: [] for f in EVAL_FIELDS}

    for r in valid:
        gt = r["ground_truth"]
        pred = r["prediction"]
        for field in EVAL_FIELDS:
            if field in gt and field in pred:
                field_true[field].append(int(bool(gt[field])))
                field_pred[field].append(int(bool(pred[field])))

    # Print per-field metrics
    print(f"\n{'=' * 70}")
    print(f"CLASSIFICATION REPORT — {_SUMMARIZER_MODEL} - {_ANALYZER_MODEL}")
    print(f"{'=' * 70}")
    print(
        f"{'Field':<20s} {'Acc':>6s} {'Prec':>6s} {'Rec':>6s} "
        f"{'F1':>6s} {'N':>4s} {'TP':>4s} {'FP':>4s} {'FN':>4s} {'TN':>4s}"
    )
    print("-" * 70)

    all_true: List[int] = []
    all_pred: List[int] = []

    for field in EVAL_FIELDS:
        yt = field_true[field]
        yp = field_pred[field]
        if not yt:
            print(f"{field:<20s} {'N/A':>6s}")
            continue

        acc = accuracy_score(yt, yp)
        prec = precision_score(yt, yp, zero_division=0)
        rec = recall_score(yt, yp, zero_division=0)
        f1 = f1_score(yt, yp, zero_division=0)

        tp = sum(1 for t, p in zip(yt, yp) if t == 1 and p == 1)
        fp = sum(1 for t, p in zip(yt, yp) if t == 0 and p == 1)
        fn = sum(1 for t, p in zip(yt, yp) if t == 1 and p == 0)
        tn = sum(1 for t, p in zip(yt, yp) if t == 0 and p == 0)

        print(
            f"{field:<20s} {acc:>5.1%} {prec:>5.1%} {rec:>5.1%} "
            f"{f1:>5.1%} {len(yt):>4d} {tp:>4d} {fp:>4d} {fn:>4d} {tn:>4d}"
        )

        all_true.extend(yt)
        all_pred.extend(yp)

    # Overall micro-averaged
    if all_true:
        acc = accuracy_score(all_true, all_pred)
        prec = precision_score(all_true, all_pred, zero_division=0)
        rec = recall_score(all_true, all_pred, zero_division=0)
        f1 = f1_score(all_true, all_pred, zero_division=0)
        print("-" * 70)
        print(
            f"{'OVERALL (micro)':<20s} {acc:>5.1%} {prec:>5.1%} {rec:>5.1%} "
            f"{f1:>5.1%} {len(all_true):>4d}"
        )

    print(f"{'=' * 70}")
    print(f"\nTotal: {len(eval_data)} | Evaluated: {len(valid)} | Errors: {len(errors)}")

    # Print mismatches for debugging
    mismatches = []
    for r in valid:
        gt = r["ground_truth"]
        pred = r["prediction"]
        misses = []
        for field in EVAL_FIELDS:
            if field in gt and field in pred and bool(gt[field]) != bool(pred[field]):
                misses.append(f"{field}(got={pred[field]}, exp={gt[field]})")
        if misses:
            mismatches.append(f"  {r['job_title']}: {', '.join(misses)}")

    if mismatches:
        print(f"\nMismatches ({len(mismatches)}):")
        for m in mismatches:
            print(m)

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  {e['job_title']}: {e['prediction'].get('error')}")


def main():
    asyncio.run(run_eval())



if __name__ == "__main__":
    main()
