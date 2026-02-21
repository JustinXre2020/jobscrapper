"""End-to-end evaluation test suite — runs full pipeline on real job data.

Loads 60 real jobs from data/evaluated_jobs.json, runs each through
summarizer → analyzer (with deterministic overrides), and compares
predicted booleans against ground-truth labels.

Metrics: precision, recall, accuracy, F1 per boolean field.

Requires OPENROUTER_API_KEY. Run with:
    pytest tests/test_eval.py -v --tb=short
"""

import asyncio
import json
from loguru import logger
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

import pytest
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

from agent.nodes.analyzer import analyzer_node
from agent.nodes.summarizer import summarizer_node
from infra.llm_client import LLMClient


EVAL_FIELDS = [
    "keyword_match",
    "visa_sponsorship",
    "entry_level",
    "is_internship",
    "requires_phd",
]

DATA_PATH = Path(__file__).parent.parent / "data" / "evaluated_jobs.json"

ACCURACY_THRESHOLD = 0.75

ALL_SEARCH_TERMS = ["software engineer", "data analyst", "data engineer", "product manager"]

CONCURRENCY = 5


def _load_eval_data() -> List[Dict[str, Any]]:
    """Load evaluated jobs, returning list of (job_without_eval, ground_truth) tuples."""
    with open(DATA_PATH) as f:
        data = json.load(f)

    results = []
    for job in data["jobs"]:
        job_copy = deepcopy(job)
        ground_truth = job_copy.pop("evaluation", {})
        results.append({"job": job_copy, "ground_truth": ground_truth})
    return results


def _infer_search_terms(title: str) -> List[str]:
    """Infer the most likely search terms from a job title."""
    t = title.lower()
    if "product manager" in t or "product management" in t:
        return ["product manager"]
    if "data engineer" in t:
        return ["data engineer"]
    if "data analyst" in t or "data analysis" in t:
        return ["data analyst"]
    if any(w in t for w in ("software", "developer", "swe")):
        return ["software engineer"]
    if "engineer" in t and "data" not in t:
        return ["software engineer"]
    if "data" in t and "analyst" in t:
        return ["data analyst"]
    if "data" in t and "engineer" in t:
        return ["data engineer"]
    if "data" in t:
        return ["data analyst", "data engineer"]
    if "analyst" in t:
        return ["data analyst"]
    if "manager" in t:
        return ["product manager"]
    if "engineer" in t:
        return ["software engineer"]
    return ALL_SEARCH_TERMS


async def _run_pipeline(
    job: Dict[str, Any], search_terms: List[str], llm_client: LLMClient
) -> Dict[str, Any]:
    """Run a single job through summarizer → analyzer."""
    state = {
        "job": job,
        "search_terms": search_terms,
        "summary": None,
        "evaluation": None,
        "accumulated_feedback": [],
        "error": None,
        "skipped": False,
    }

    summary_result = await summarizer_node(state, llm_client)
    if summary_result.get("skipped") or summary_result.get("error"):
        return {"error": summary_result.get("error", "Skipped")}

    state["summary"] = summary_result["summary"]

    eval_result = await analyzer_node(state, llm_client)
    if eval_result.get("error") and not eval_result.get("evaluation"):
        return {"error": eval_result["error"]}

    return eval_result.get("evaluation", {})


async def _run_all(
    eval_data: List[Dict[str, Any]], llm_client: LLMClient
) -> List[Dict[str, Any]]:
    """Run all jobs through the pipeline with bounded concurrency."""
    semaphore = asyncio.Semaphore(CONCURRENCY)
    results = []

    async def _process(item: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            job = item["job"]
            title = job.get("title", "")
            search_terms = _infer_search_terms(title)
            try:
                prediction = await _run_pipeline(job, search_terms, llm_client)
            except Exception as e:
                logger.error(f"Pipeline error [{title}]: {e}")
                prediction = {"error": str(e)}
            return {
                "job_title": title,
                "ground_truth": item["ground_truth"],
                "prediction": prediction,
            }

    tasks = [_process(item) for item in eval_data]
    results = await asyncio.gather(*tasks)
    return list(results)


def _collect_labels(
    results: List[Dict[str, Any]],
) -> Dict[str, Dict[str, List[bool]]]:
    """Collect y_true and y_pred per field from pipeline results."""
    labels: Dict[str, Dict[str, List[bool]]] = {
        field: {"y_true": [], "y_pred": []} for field in EVAL_FIELDS
    }

    for r in results:
        gt = r["ground_truth"]
        pred = r["prediction"]
        if pred.get("error"):
            continue
        for field in EVAL_FIELDS:
            if field in gt and field in pred:
                labels[field]["y_true"].append(bool(gt[field]))
                labels[field]["y_pred"].append(bool(pred[field]))

    return labels


def _compute_metrics(y_true: List[bool], y_pred: List[bool]) -> Dict[str, float]:
    """Compute classification metrics for a single field."""
    if not y_true:
        return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
    }


def _print_report(
    labels: Dict[str, Dict[str, List[bool]]], model_name: str, total: int, errors: int
) -> Dict[str, Dict[str, float]]:
    """Print classification report and return metrics dict."""
    print(f"\n{'=' * 70}")
    print(f"Model: {model_name}")
    print(f"Jobs: {total} total, {total - errors} evaluated, {errors} errors")
    print(f"{'=' * 70}")
    print(
        f"{'Field':<20s} {'Acc':>6s} {'Prec':>6s} {'Rec':>6s} {'F1':>6s} {'N':>4s}"
    )
    print("-" * 48)

    all_metrics = {}
    for field in EVAL_FIELDS:
        y_true = labels[field]["y_true"]
        y_pred = labels[field]["y_pred"]
        m = _compute_metrics(y_true, y_pred)
        all_metrics[field] = m
        print(
            f"{field:<20s} {m['accuracy']:>5.1%} {m['precision']:>5.1%} "
            f"{m['recall']:>5.1%} {m['f1']:>5.1%} {len(y_true):>4d}"
        )

    # Overall (micro-average across all fields)
    all_true = []
    all_pred = []
    for field in EVAL_FIELDS:
        all_true.extend(labels[field]["y_true"])
        all_pred.extend(labels[field]["y_pred"])

    if all_true:
        overall = _compute_metrics(all_true, all_pred)
        print("-" * 48)
        print(
            f"{'OVERALL (micro)':<20s} {overall['accuracy']:>5.1%} "
            f"{overall['precision']:>5.1%} {overall['recall']:>5.1%} "
            f"{overall['f1']:>5.1%} {len(all_true):>4d}"
        )
        all_metrics["overall"] = overall

    print(f"{'=' * 70}\n")
    return all_metrics


@pytest.mark.live
class TestFullPipelineEval:
    """Run full summarizer → analyzer on 60 real jobs and measure accuracy."""

    @pytest.mark.asyncio
    async def test_eval_metrics(self, llm_client: LLMClient) -> None:
        """End-to-end classification metrics on all eval jobs."""
        eval_data = _load_eval_data()
        results = await _run_all(eval_data, llm_client)

        errors = sum(1 for r in results if r["prediction"].get("error"))
        labels = _collect_labels(results)

        model_name = getattr(llm_client, "model", "unknown")
        all_metrics = _print_report(labels, model_name, len(eval_data), errors)

        # Log individual mismatches for debugging
        for r in results:
            pred = r["prediction"]
            gt = r["ground_truth"]
            if pred.get("error"):
                continue
            misses = []
            for field in EVAL_FIELDS:
                if field in gt and field in pred and bool(gt[field]) != bool(pred[field]):
                    misses.append(f"{field}: got={pred[field]} expected={gt[field]}")
            if misses:
                logger.warning(f"MISS [{r['job_title']}]: {'; '.join(misses)}")

        # Assert minimum accuracy thresholds
        overall = all_metrics.get("overall", {})
        assert overall.get("accuracy", 0) >= ACCURACY_THRESHOLD, (
            f"Overall accuracy {overall.get('accuracy', 0):.1%} "
            f"below threshold {ACCURACY_THRESHOLD:.0%}"
        )

