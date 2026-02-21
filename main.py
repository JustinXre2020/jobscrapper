"""
Job Hunter Sentinel - Main Orchestration Script
Coordinates scraping, deduplication, and email dispatch
Supports multi-recipient with per-recipient search terms and sponsorship filtering
"""
import os
import sys
from typing import List, Dict
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd
from loguru import logger
from infra.logging_config import configure_logging

# Import custom modules
from scraper import JobScraper
from storage.database import JobDatabase
from notification.email_sender import EmailSender
from storage.data_manager import DataManager

from filtering.job_filter import OpenRouterLLMFilter

from config import parse_recipients, get_all_search_terms, mask_email, get_results_wanted, get_scrape_queries, DEFAULT_RESULTS_WANTED

load_dotenv()


def setup_logging() -> str:
    """Configure logging to output to both console and file."""
    return configure_logging(
        log_file_prefix="job_hunter",
        third_party_levels={
            "llm_filter": "DEBUG",
            "aiohttp": "WARNING",
            "urllib3": "WARNING",
        },
    )


class JobHunterSentinel:
    """Main orchestrator for the job hunting automation system"""

    def __init__(self):
        """Initialize all components"""
        logger.info("🚀 Initializing Job Hunter Sentinel...")

        try:
            self.scraper = JobScraper()
            self.database = JobDatabase()
            self.email_sender = EmailSender()
            self.data_manager = DataManager()

            # Load recipients and their search terms
            self.recipients = parse_recipients()
            self.all_search_terms = get_all_search_terms(self.recipients)

            # Configuration
            self.locations = self._get_list_config("LOCATIONS", ["San Francisco, CA"])
            self.hours_old = int(os.getenv("HOURS_OLD", "24"))
            self.use_llm_filter = os.getenv("USE_LLM_FILTER", "true").lower() == "true"
            self.llm_workers = int(os.getenv("LLM_WORKERS", "0"))  # 0 = auto-detect based on RAM

            # Initialize LLM filter if enabled
            self.llm_filter = None
            if self.use_llm_filter:
                logger.info("🤖 Initializing OpenRouter LLM Filter...")
                self.llm_filter = OpenRouterLLMFilter()

            logger.info("✅ Configuration loaded:")
            logger.info(f"   Recipients: {len(self.recipients)}")
            for r in self.recipients:
                logger.info(f"     - {mask_email(r.email)} (needs_sponsorship={r.needs_sponsorship}, terms={r.search_terms})")
            logger.info(f"   All Search Terms: {self.all_search_terms}")
            logger.info(f"   Locations: {self.locations}")
            logger.info(f"   Results Wanted: per-term (default={DEFAULT_RESULTS_WANTED})")
            logger.info(f"   Time Window: {self.hours_old} hours")
            logger.info(f"   LLM Filter: {'Enabled' if self.use_llm_filter else 'Disabled'}")
            logger.info(f"   LLM Workers: {self.llm_workers if self.llm_workers > 0 else 'auto'}")

        except Exception as e:
            logger.exception(f"❌ Initialization failed: {e}")
            sys.exit(1)

    def _get_list_config(self, key: str, default: List[str]) -> List[str]:
        """Parse comma-separated config value"""
        value = os.getenv(key)
        if not value:
            return default
        return [item.strip() for item in value.split(",") if item.strip()]

    def run(self):
        """Execute the full job hunting workflow with sequential keyword processing"""
        start_time = datetime.now()
        logger.info(f"\n{'='*60}")
        logger.info("🎯 Job Hunter Sentinel - Daily Run")
        logger.info(f"⏰ Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*60}\n")

        try:
            # Track jobs by search term for per-recipient filtering
            jobs_by_term: Dict[str, List[Dict]] = {}
            total_scraped = 0
            total_new = 0
            total_filtered = 0

            # Process each search term sequentially
            for term_idx, search_term in enumerate(self.all_search_terms, 1):
                logger.info(f"\n{'='*60}")
                logger.info(f"🔍 Processing search term {term_idx}/{len(self.all_search_terms)}: '{search_term}'")
                logger.info(f"{'='*60}")

                # Step 1: Scrape Jobs for THIS keyword only
                logger.info(f"\n📡 STEP 1: Scraping job postings for '{search_term}'...")
                logger.info("-" * 60)

                # Get per-term results count and scrape queries (groups expand)
                results_wanted = get_results_wanted(search_term)
                scrape_queries = get_scrape_queries(search_term)
                logger.info(f"   Scraping {results_wanted} results for queries: {scrape_queries}")

                jobs_df = self.scraper.scrape_multiple_queries(
                    search_terms=scrape_queries,
                    locations=self.locations,
                    results_wanted=results_wanted,
                    hours_old=self.hours_old
                )

                if jobs_df.empty:
                    logger.warning(f"   ⚠️ No jobs found for '{search_term}'")
                    jobs_by_term[search_term] = []
                    continue

                scraped_count = len(jobs_df)
                total_scraped += scraped_count
                logger.info(f"   ✅ Scraped {scraped_count} jobs for '{search_term}'")

                # Step 2: Deduplication (before LLM filtering to save inference time)
                logger.info(f"\n🔍 STEP 2: Checking for duplicate jobs...")
                logger.info("-" * 60)
                jobs_list = jobs_df.to_dict('records')
                new_jobs = self.database.filter_new_jobs(jobs_list)

                if not new_jobs:
                    logger.warning(f"   ⚠️ All jobs for '{search_term}' were already sent")
                    jobs_by_term[search_term] = []
                    continue

                new_count = len(new_jobs)
                total_new += new_count
                logger.info(f"   ✅ {new_count} new jobs for '{search_term}'")

                # Step 2.5: Save ALL new jobs before filtering (for data collection)
                logger.info(f"\n💾 Saving {new_count} new jobs to storage...")
                safe_term = search_term.replace(' ', '_').replace('/', '_')[:30]
                self.data_manager.save_jobs(new_jobs, timestamp=start_time, prefix=f"all_jobs_{safe_term}")

                # Step 3: LLM-based filtering for entry-level and H1B-friendly jobs
                logger.info(f"\n🤖 STEP 3: LLM filtering for '{search_term}'...")
                logger.info("-" * 60)

                # Use parallel filtering (auto-detects workers based on RAM if llm_workers=0)
                filtered_jobs = self.llm_filter.filter_jobs_parallel(
                    new_jobs, [search_term], num_workers=self.llm_workers
                )

                filtered_count = len(filtered_jobs)
                total_filtered += filtered_count
                logger.info(f"   ✅ {filtered_count} jobs passed filters for '{search_term}'")

                # Store filtered jobs for this term
                jobs_by_term[search_term] = filtered_jobs

                # Save filtered data
                if filtered_jobs:
                    self.data_manager.save_jobs(filtered_jobs, timestamp=start_time, prefix=f"filtered_jobs_{safe_term}")

            # Check if we have any jobs to send
            all_jobs_count = sum(len(jobs) for jobs in jobs_by_term.values())

            if all_jobs_count == 0:
                logger.warning("\n⚠️ No jobs passed filters across all search terms. Sending empty notification...")
                self.email_sender.send_empty_notification()
                self._log_summary(start_time, total_scraped, 0, {})
                return

            # Step 4: Send Emails (per-recipient filtering by term + sponsorship)
            logger.info(f"\n📧 STEP 4: Sending email digests to {len(self.recipients)} recipient(s)...")
            logger.info("-" * 60)
            email_results = self.email_sender.send_daily_digest(jobs_by_term)

            # Step 5: Mark ALL unique jobs as sent (regardless of recipient)
            logger.info(f"\n💾 STEP 5: Marking jobs as sent in database...")
            logger.info("-" * 60)

            # Collect all unique jobs across all terms
            all_unique_jobs = []
            seen_urls = set()
            for jobs in jobs_by_term.values():
                for job in jobs:
                    url = job.get('job_url')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_unique_jobs.append(job)

            for job in all_unique_jobs:
                self.database.mark_as_sent(
                    job_url=job.get('job_url', ''),
                    title=job.get('title', ''),
                    company=job.get('company', ''),
                    location=job.get('location', ''),
                    score=0,
                    metadata={
                        'site': job.get('site', '')
                    }
                )

            logger.info(f"   ✅ Marked {len(all_unique_jobs)} unique jobs as sent")

            # Step 6: Show data storage statistics
            logger.info(f"\n📊 STEP 6: Data storage statistics...")
            logger.info("-" * 60)
            stats = self.data_manager.get_statistics()
            logger.info(f"   Total files: {stats['total_files']} ({stats['json_files']} JSON, {stats['csv_files']} CSV)")
            logger.info(f"   Total jobs stored: {stats['total_jobs']}")
            logger.info(f"   Storage size: {stats['total_size_mb']:.2f} MB")
            logger.info(f"   Oldest file: {stats['oldest_file']}")
            logger.info(f"   Newest file: {stats['newest_file']}")

            # Cleanup old data files (older than 7 days)
            self.data_manager.cleanup_old_files(days=7)

            # Summary
            self._log_summary(start_time, total_scraped, total_filtered, email_results)

        except KeyboardInterrupt:
            logger.warning("\n\n⚠️ Process interrupted by user")
            sys.exit(0)
        except Exception as e:
            logger.exception(f"\n\n❌ Fatal error: {e}")
            sys.exit(1)

    def _log_summary(
        self,
        start_time: datetime,
        scraped: int,
        filtered: int,
        email_results: Dict[str, bool]
    ):
        """Log execution summary"""
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Calculate email stats
        total_recipients = len(email_results) if email_results else 0
        successful_emails = sum(1 for success in email_results.values() if success) if email_results else 0

        logger.info(f"\n{'='*60}")
        logger.info("📊 EXECUTION SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"⏱️  Duration: {duration:.1f} seconds")
        logger.info(f"📡 Jobs Scraped: {scraped}")
        logger.info(f"🔍 Jobs Filtered: {filtered}")
        logger.info(f"📧 Email Results: {successful_emails}/{total_recipients} successful")

        if email_results:
            for email, success in email_results.items():
                status = "✅" if success else "❌"
                logger.info(f"   {status} {email}")

        overall_status = 'SUCCESS' if filtered > 0 and successful_emails > 0 else 'NO NEW JOBS'
        logger.info(f"✅ Status: {overall_status}")
        logger.info(f"{'='*60}\n")


def main():
    """Main entry point"""
    # Setup logging first
    log_file = setup_logging()
    main_logger = logger
    main_logger.info(f"📝 Logging to: {log_file}")

    try:
        sentinel = JobHunterSentinel()
        sentinel.run()
    except Exception as e:
        main_logger.exception(f"❌ Application failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
