"""Backwards-compatible public API for the LangGraph agent workflow.

Current workflow is strictly per-job:
    Summarizer -> (3 parallel Analyzer calls) -> majority-voted evaluation

Each node uses its own LLM client configured via settings:
    summarizer_provider / summarizer_model  -- for the Summarizer node
    analyzer_provider   / analyzer_model    -- for the Analyzer ensemble
"""

import asyncio
from loguru import logger
from typing import Dict, List

from agent.feedback.store import feedback_store
from agent.graph import build_graph, run_single_job
from infra.llm_client import create_llm_client
from utils.config import settings


class LLMFilter:
    """Filter jobs using the per-job LangGraph workflow.

    The Summarizer and Analyzer nodes each receive their own ``BaseLLMClient``,
    allowing them to target different models or even different inference backends.
    """

    def __init__(
        self,
        concurrency: int = 0,
        rate_limit_delay: float = 60,
    ) -> None:
        """
        Args:
            model: Legacy single-model override. When provided, sets the Analyzer
                   model to this value (for backwards compatibility). Per-node
                   settings take precedence over this argument.
            concurrency: Max number of jobs processed in parallel (0 = use settings).
            rate_limit_delay: Seconds to wait between concurrency-sized batches.
        """
        # Build per-node clients from settings; `model` arg overrides analyzer model
        self.summarizer_client = create_llm_client(
            provider=settings.summarizer_provider, model=settings.summarizer_model
        )
        self.analyzer_client = create_llm_client(
            provider=settings.analyzer_provider, model=settings.analyzer_model
        )

        self.feedback_store = feedback_store
        self.concurrency = concurrency or settings.agent_concurrency
        self.rate_limit_delay = rate_limit_delay
        self.compiled_graph = build_graph(self.summarizer_client, self.analyzer_client)

        logger.info("Agent workflow LLM Filter initialized (single-job ensemble mode)")
        logger.info(f"   Summarizer: {self.summarizer_client.model} ({settings.summarizer_provider})")
        logger.info(f"   Analyzer:   {self.analyzer_client.model} ({settings.analyzer_provider})")
        logger.info(f"   Batch size: {self.concurrency}")

    async def _process_single_job(
        self,
        job: Dict,
        search_terms: List[str],
        accumulated_feedback: List[str],
    ) -> Dict:
        """Process a single job through the per-job workflow."""
        job_title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")

        try:
            final_state = await run_single_job(
                self.compiled_graph,
                job,
                search_terms,
                accumulated_feedback=accumulated_feedback,
            )

            if final_state.get("skipped"):
                return {
                    "keyword_match": False,
                    "visa_sponsorship": False,
                    "entry_level": False,
                    "requires_phd": False,
                    "is_internship": False,
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
                        "entry_level": False,
                        "requires_phd": True,
                        "is_internship": True,
                        "reason": "Rate limited (429) - filtered out",
                        "error": True,
                        "rate_limited": True,
                        "job_title": job_title,
                        "company": company,
                    }
                return {
                    "keyword_match": True,
                    "visa_sponsorship": True,
                    "entry_level": True,
                    "requires_phd": False,
                    "is_internship": False,
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
                "entry_level": True,
                "requires_phd": False,
                "is_internship": False,
                "reason": f"Error: {str(e)[:50]}",
                "error": True,
                "job_title": job_title,
                "company": company,
            }

    async def _filter_jobs(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        verbose: bool = True,
    ) -> List[Dict]:
        """Filter jobs with per-job graph execution in concurrent batches."""
        total = len(jobs_list)
        logger.info(f"   Starting single-job ensemble workflow with batch_size={self.concurrency}...")
        logger.info(f"   Processing {total} jobs...")

        accumulated_feedback = self.feedback_store.load_feedback()
        if accumulated_feedback:
            logger.info(f"   Loaded {len(accumulated_feedback)} past corrections for Analyzer prompt")

        results: List[tuple] = []
        completed = 0

        for batch_idx in range(0, total, self.concurrency):
            batch = jobs_list[batch_idx : batch_idx + self.concurrency]

            evaluations = await asyncio.gather(
                *[
                    self._process_single_job(job, search_terms, accumulated_feedback)
                    for job in batch
                ]
            )

            results.extend((job, evaluation) for job, evaluation in zip(batch, evaluations))

            if batch_idx + self.concurrency < total:
                await asyncio.sleep(self.rate_limit_delay)
            completed += len(batch)

            if verbose:
                logger.info(f"   Evaluated {min(completed, total)}/{total}...")

        return self._extract_filtered_jobs_from_pairs(results, verbose)

    def _extract_filtered_jobs_from_pairs(
        self, results: List[tuple], verbose: bool = True
    ) -> List[Dict]:
        """Extract filtered jobs from (job, evaluation) pairs."""
        filtered = []
        excluded_keyword = 0
        excluded_experience = 0
        excluded_phd = 0
        excluded_internship = 0
        skipped = 0
        error = 0
        no_visa_count = 0

        for job, evaluation in results:
            if evaluation.get("error", False):
                error += 1
                continue

            if evaluation.get("skipped", False):
                skipped += 1
                continue

            if not evaluation.get("keyword_match", False):
                excluded_keyword += 1
                continue

            if not evaluation.get("visa_sponsorship", False):
                no_visa_count += 1

            if not evaluation.get("entry_level", False):
                excluded_experience += 1
                continue

            if evaluation.get("requires_phd", False):
                excluded_phd += 1
                continue

            if evaluation.get("is_internship", False):
                excluded_internship += 1
                continue

            job["llm_evaluation"] = evaluation
            filtered.append(job)

        if verbose:
            self._log_filter_stats(
                error,
                skipped,
                excluded_keyword,
                excluded_experience,
                excluded_phd,
                excluded_internship,
                no_visa_count,
                len(filtered),
            )

        return filtered

    @staticmethod
    def _log_filter_stats(
        error, skipped, excluded_keyword, excluded_experience,
        excluded_phd, excluded_internship, no_visa_count, filtered_count,
    ):
        logger.info(f"   Skipped {error} errored jobs (error calling OpenRouter)")
        logger.info(f"   Skipped {skipped} jobs (no description)")
        logger.info(f"   Excluded {excluded_keyword} jobs (keyword mismatch)")
        logger.info(f"   Excluded {excluded_experience} jobs (not entry-level)")
        logger.info(f"   Excluded {excluded_phd} jobs (PhD required)")
        logger.info(f"   Excluded {excluded_internship} jobs (internship)")
        logger.info(f"   Tracked {no_visa_count} jobs without visa sponsorship (not filtered)")
        logger.info(f"   {filtered_count} jobs passed agent workflow filter")

    def batch_filter_jobs(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        verbose: bool = True,
    ) -> List[Dict]:
        """Backwards-compatible method that uses async agent workflow."""
        return asyncio.run(self._filter_jobs(jobs_list, search_terms, verbose))
