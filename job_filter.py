"""Backwards-compatible public API for the LangGraph agent workflow.

Drop-in replacement for llm_filter.py's OpenRouterLLMFilter class.
Exposes the same class name, method signatures, and output format.
"""

import os
import asyncio
import logging
from typing import Dict, List, Optional

from infra.llm_client import LLMClient
from agent.graph import build_graph, run_single_job
from agent.feedback.store import FeedbackStore

logger = logging.getLogger(__name__)

AGENT_CONCURRENCY = int(os.getenv("AGENT_CONCURRENCY", "50"))


class OpenRouterLLMFilter:
    """Filter jobs using the 3-node LangGraph agent workflow.

    Backwards-compatible with the old llm_filter.OpenRouterLLMFilter.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        concurrency: int = AGENT_CONCURRENCY,
        rate_limit_delay: float = 60,
    ) -> None:
        """Initialize the agent-based LLM filter.

        Args:
            model: OpenRouter model identifier (reads from env if None).
            concurrency: Max jobs processed simultaneously per batch.
            rate_limit_delay: Delay in seconds between batches.
        """
        self.llm_client = LLMClient(model=model)
        self.model = self.llm_client.model
        self.concurrency = concurrency
        self.rate_limit_delay = rate_limit_delay
        self.compiled_graph = build_graph(self.llm_client)
        self.feedback_store = FeedbackStore()

        self.is_free_model = ":free" in self.model.lower()

        logger.info("Agent workflow LLM Filter initialized")
        logger.info(f"   Model: {self.model}")
        logger.info(f"   Batch size: {self.concurrency}")
        logger.info(f"   Reviewer sample rate: {os.getenv('REVIEWER_SAMPLE_RATE', '0.2')}")
        if self.is_free_model:
            logger.warning("   Free model detected - rate limited (~19 req/min)")

    async def _process_single_job(
        self,
        job: Dict,
        search_terms: List[str],
        accumulated_feedback: List[str],
    ) -> Dict:
        """Process a single job through the agent workflow.

        Returns the final evaluation dict with job metadata.
        """
        job_title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")

        try:
            final_state = await run_single_job(
                self.compiled_graph,
                job,
                search_terms,
                accumulated_feedback=accumulated_feedback,
            )

            # Check if skipped
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

            # Check for errors without evaluation
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

            # Save reviewer feedback if the review disagreed
            if final_state.get("review_passed") is False and final_state.get("review_feedback"):
                self.feedback_store.save_feedback(
                    feedback=final_state["review_feedback"],
                    job_title=job_title,
                    job_company=company,
                )

            return evaluation

        except Exception as e:
            logger.error(f"Unexpected error processing {job_title} @ {company}: {e}", exc_info=True)
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

    async def filter_jobs_async(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        verbose: bool = True,
    ) -> List[Dict]:
        """Filter jobs using the agent workflow with async concurrent batches.

        Args:
            jobs_list: List of job dictionaries.
            search_terms: Target job roles to match.
            verbose: Print progress.

        Returns:
            Filtered list of jobs that pass all criteria.
        """
        total = len(jobs_list)
        if total == 0:
            return []

        logger.info(f"   Starting agent workflow filtering with batch_size={self.concurrency}...")
        logger.info(f"   Processing {total} jobs...")

        # Load accumulated feedback once per batch run
        accumulated_feedback = self.feedback_store.load_feedback()
        if accumulated_feedback:
            logger.info(f"   Loaded {len(accumulated_feedback)} past corrections for Analyzer prompt")

        results: List[tuple] = []
        completed = 0

        for batch_idx in range(0, total, self.concurrency):
            batch = jobs_list[batch_idx : batch_idx + self.concurrency]

            async with asyncio.TaskGroup() as tg:
                tasks = [
                    (
                        job,
                        tg.create_task(
                            self._process_single_job(job, search_terms, accumulated_feedback)
                        ),
                    )
                    for job in batch
                ]

            # Wait for rate limiting between batches
            await asyncio.sleep(self.rate_limit_delay)

            results += [(job, task_future.result()) for job, task_future in tasks]
            completed += len(batch)

            if verbose:
                logger.info(f"   Evaluated {min(completed, total)}/{total}...")

        # Process results (same logic as legacy llm_filter)
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

        logger.info(f"   Skipped {error} errored jobs (error calling OpenRouter)")
        logger.info(f"   Skipped {skipped} jobs (no description)")
        logger.info(f"   Excluded {excluded_keyword} jobs (keyword mismatch)")
        logger.info(f"   Excluded {excluded_experience} jobs (not entry-level)")
        logger.info(f"   Excluded {excluded_phd} jobs (PhD required)")
        logger.info(f"   Excluded {excluded_internship} jobs (internship)")
        logger.info(f"   Tracked {no_visa_count} jobs without visa sponsorship (not filtered)")
        logger.info(f"   {len(filtered)} jobs passed agent workflow filter")

        return filtered

    def filter_jobs(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        verbose: bool = True,
    ) -> List[Dict]:
        """Synchronous wrapper for filter_jobs_async."""
        return asyncio.run(self.filter_jobs_async(jobs_list, search_terms, verbose))

    def filter_jobs_parallel(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        num_workers: int = 0,
        verbose: bool = True,
    ) -> List[Dict]:
        """Backwards-compatible method that uses async agent workflow.

        Note: num_workers is ignored; concurrency is controlled by AGENT_CONCURRENCY.
        """
        if num_workers > 0:
            logger.warning(
                f"   num_workers={num_workers} ignored, "
                f"using agent batch size={self.concurrency}"
            )
        return self.filter_jobs(jobs_list, search_terms, verbose)
