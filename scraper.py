"""
Job Scraper Engine
Aggregates job postings from multiple sources using python-jobspy
"""
import os
import time
import random
import logging
from typing import List, Dict, Optional
from jobspy import scrape_jobs
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class JobScraper:
    """Job scraper with retry logic and error handling"""
    
    def __init__(self):
        self.sites = [item.strip() for item in os.getenv("SITES", "indeed").split(",") if item.strip()]
        self.max_retries = 3
        self.base_delay = 2  # seconds
        
    def scrape_with_retry(
        self,
        search_term: str,
        location: str,
        results_wanted: int = 20,
        hours_old: int = 24
    ) -> Optional[pd.DataFrame]:
        """
        Scrape jobs with exponential backoff retry logic
        
        Args:
            search_term: Job title or keywords
            location: Geographic location
            results_wanted: Number of results per site
            hours_old: Only fetch jobs posted within this timeframe
            
        Returns:
            DataFrame with job listings or None if all retries fail
        """
        for attempt in range(self.max_retries):
            try:
                logger.info(f"🔍 Scraping: '{search_term}' in '{location}' (Attempt {attempt + 1}/{self.max_retries})")

                jobs = scrape_jobs(
                    site_name=self.sites,
                    search_term=search_term,
                    location=location,
                    results_wanted=results_wanted,
                    hours_old=hours_old,
                    job_type="fulltime",
                    country_indeed='USA',
                    linkedin_fetch_description=False,  # Fast initial scrape
                    description_format="markdown"
                )

                if jobs is not None and not jobs.empty:
                    logger.info(f"✅ Found {len(jobs)} jobs")
                    return jobs
                else:
                    logger.warning(f"⚠️ No jobs found for '{search_term}' in '{location}'")
                    return None

            except Exception as e:
                error_msg = str(e)

                # Handle 429 (Rate Limit) errors
                if "429" in error_msg or "rate limit" in error_msg.lower():
                    delay = self.base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"⏳ Rate limited (429). Backing off for {delay:.1f}s...")
                    time.sleep(delay)
                    continue

                # Handle other errors
                logger.error(f"❌ Error on attempt {attempt + 1}: {error_msg}")

                if attempt < self.max_retries - 1:
                    delay = self.base_delay + random.uniform(0, 1)
                    time.sleep(delay)
                else:
                    logger.error(f"🚫 All retries failed for '{search_term}' in '{location}'")
                    return None

        return None
    
    def scrape_multiple_queries(
        self,
        search_terms: List[str],
        locations: List[str],
        results_wanted: int = 20,
        hours_old: int = 24
    ) -> pd.DataFrame:
        """
        Scrape jobs for multiple search terms and locations
        
        Args:
            search_terms: List of job titles/keywords
            locations: List of geographic locations
            results_wanted: Results per query
            hours_old: Recency filter in hours
            
        Returns:
            Combined DataFrame with all results
        """
        all_jobs = []
        
        for search_term in search_terms:
            for location in locations:
                jobs = self.scrape_with_retry(
                    search_term=search_term,
                    location=location,
                    results_wanted=results_wanted,
                    hours_old=hours_old
                )
                
                if jobs is not None:
                    all_jobs.append(jobs)
                
                # Polite delay between queries
                time.sleep(random.uniform(1, 3))
        
        if not all_jobs:
            logger.warning("⚠️ No jobs found across all queries")
            return pd.DataFrame()

        combined = pd.concat(all_jobs, ignore_index=True)

        # Remove duplicates based on job_url
        combined = combined.drop_duplicates(subset=['job_url'], keep='first')

        logger.info(f"📊 Total unique jobs scraped: {len(combined)}")
        return combined
    
    def fetch_linkedin_details(self, jobs_df: pd.DataFrame) -> pd.DataFrame:
        """
        Fetch detailed descriptions for LinkedIn jobs that passed initial screening
        
        Args:
            jobs_df: DataFrame with jobs to fetch details for
            
        Returns:
            Updated DataFrame with full descriptions
        """
        linkedin_jobs = jobs_df[jobs_df['site'] == 'linkedin'].copy()
        
        if linkedin_jobs.empty:
            return jobs_df
        
        logger.info(f"📄 Fetching detailed descriptions for {len(linkedin_jobs)} LinkedIn jobs...")
        
        for idx, job in linkedin_jobs.iterrows():
            try:
                # Re-scrape with description enabled
                detailed = scrape_jobs(
                    site_name=["linkedin"],
                    job_url=job['job_url'],
                    linkedin_fetch_description=True,
                    description_format="markdown"
                )
                
                if detailed is not None and not detailed.empty:
                    jobs_df.at[idx, 'description'] = detailed.iloc[0]['description']
                    
                time.sleep(random.uniform(2, 4))  # Respectful rate limiting
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to fetch details for {job['job_url']}: {e}")
                continue
        
        return jobs_df


def main():
    """Test the scraper"""
    scraper = JobScraper()
    
    # Load configuration
    search_terms = os.getenv("SEARCH_TERMS", "software engineer").split(",")
    locations = os.getenv("LOCATIONS", "San Francisco, CA").split(",")
    results_wanted = int(os.getenv("RESULTS_WANTED", "20"))
    hours_old = int(os.getenv("HOURS_OLD", "24"))
    
    # Clean up terms
    search_terms = [term.strip() for term in search_terms]
    locations = [loc.strip() for loc in locations]
    
    # Scrape
    jobs = scraper.scrape_multiple_queries(
        search_terms=search_terms,
        locations=locations,
        results_wanted=results_wanted,
        hours_old=hours_old
    )
    
    if not jobs.empty:
        logger.info("📋 Sample jobs:")
        logger.info(jobs[['title', 'company', 'location', 'site']].head())
    else:
        logger.warning("❌ No jobs found")


if __name__ == "__main__":
    main()
