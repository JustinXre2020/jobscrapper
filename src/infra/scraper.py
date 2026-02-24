"""
Job Scraper Engine
Aggregates job postings from multiple sources using python-jobspy
"""
import time
import random
from loguru import logger
from typing import List, Dict, Optional
from jobspy import scrape_jobs
import pandas as pd

from utils.config import settings


class JobScraper:
    """Job scraper with retry logic and error handling"""

    def __init__(self):
        self.sites = [s.strip() for s in settings.sites.split(",") if s.strip()]
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

        def _normalize_text(value: object) -> str:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return ""
            return " ".join(str(value).strip().lower().split())

        def _merge_locations(locations: pd.Series) -> str:
            merged_locations: List[str] = []
            for raw_location in locations:
                if raw_location is None or (isinstance(raw_location, float) and pd.isna(raw_location)):
                    continue
                for location_part in str(raw_location).split("|"):
                    location = location_part.strip()
                    if location and location not in merged_locations:
                        merged_locations.append(location)
            return " | ".join(merged_locations)

        def _merge_duplicate_rows(df: pd.DataFrame, key_builder) -> pd.DataFrame:
            if df.empty:
                return df

            grouped = df.copy()
            grouped["_dedup_key"] = grouped.apply(key_builder, axis=1)

            merged_rows = []
            for _, group in grouped.groupby("_dedup_key", sort=False, dropna=False):
                first_row = group.iloc[0].copy()
                if "location" in group.columns:
                    merged_location = _merge_locations(group["location"])
                    if merged_location:
                        first_row["location"] = merged_location
                merged_rows.append(first_row)

            merged_df = pd.DataFrame(merged_rows).reset_index(drop=True)
            return merged_df.drop(columns=["_dedup_key"], errors="ignore")

        def _url_key(row: pd.Series) -> str:
            normalized_url = _normalize_text(row.get("job_url", ""))
            return f"url:{normalized_url}" if normalized_url else f"row:{row.name}"

        def _title_company_key(row: pd.Series) -> str:
            normalized_title = _normalize_text(row.get("title", ""))
            normalized_company = _normalize_text(row.get("company", ""))
            if normalized_title and normalized_company:
                return f"title_company:{normalized_title}|{normalized_company}"
            return _url_key(row)

        # 1) Exact URL duplicates
        combined = _merge_duplicate_rows(combined, _url_key)
        # 2) Same title+company with different URLs (merge locations)
        combined = _merge_duplicate_rows(combined, _title_company_key)

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

    # Load configuration from settings
    search_terms = [t.strip() for t in settings.search_terms.split(",")]
    locations = [loc.strip() for loc in settings.locations.split(",")]
    results_wanted = settings.results_wanted
    hours_old = settings.hours_old
    
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
