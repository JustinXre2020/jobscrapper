"""
OpenRouter LLM Filter using async API calls
Filters jobs based on keyword match, visa sponsorship, and entry-level requirements
Supports asyncio for concurrent inference

OLD LOCAL INFERENCE LOGIC IS PRESERVED AT THE BOTTOM OF THIS FILE
"""
import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
from openai import AsyncOpenAI
import pandas as pd

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# OpenRouter API Configuration
OPENROUTER_API_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "liquid/lfm-2.5-1.2b-instruct:free")
_openrouter_client: Optional[AsyncOpenAI] = None


def _get_openrouter_client() -> AsyncOpenAI:
    """Get or create the shared AsyncOpenAI client for OpenRouter."""
    global _openrouter_client
    if _openrouter_client is None:
        if not OPENROUTER_API_KEY:
            raise OpenRouterError("OPENROUTER_API_KEY environment variable not set")
        _openrouter_client = AsyncOpenAI(
            base_url=OPENROUTER_API_URL,
            api_key=OPENROUTER_API_KEY,
            default_headers={
                "HTTP-Referer": "https://resume-matcher.app",
                "X-Title": "JobsWrapper-Filter",
            },
            timeout=60.0,
        )
    return _openrouter_client


class OpenRouterError(Exception):
    """Custom exception for OpenRouter API errors."""
    pass


def _safe_str(value: Any, default: str = '') -> str:
    """Safely convert value to string, handling NaN/None"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return str(value)


def _create_prompt(job: Dict, search_terms: List[str]) -> str:
    """Create prompt for job evaluation"""
    title = _safe_str(job.get('title'), 'Unknown')
    company = _safe_str(job.get('company'), 'Unknown')
    location = _safe_str(job.get('location'), 'Unknown')
    description = _safe_str(job.get('description'), '')
    search_terms_str = ", ".join(search_terms)

    prompt = f"""
        ### DATA
        Job Title: {title}
        Company: {company}
        Location: {location}
        Target Roles: [{search_terms_str}]

        Description: {description}

        ### INSTRUCTIONS
        Analyze the job posting above and extract the following data points into JSON format.

        1. keyword_match: (true/false)
        - Perform a semantic match between the "Job Title" and the "Target Roles" list.
        - Return TRUE if the job represents the same professional function as any Target Role, even if the wording differs. 
        - Ignore seniority levels (e.g., "II", "Senior", "Lead") unless the Target Role list specifically filters for them.

        2. visa_sponsorship: (true/false)
        - Does the description explicitly state they will NOT provide sponsorship?
        - Return FALSE if you see phrases like "Must be a US Citizen," "No sponsorship available," or "Work authorization required without sponsorship."
        - Return TRUE if sponsorship is mentioned as available, OR if there is no mention of work authorization requirements (assume a neutral/positive stance).

        3. is_internship: (true/false)
        - Return TRUE if the job is labeled as an "Intern," "Co-op," "Fellowship," or "Apprenticeship."

        4. entry_level: (true/false)
        - Determine if this is a "starting" role (0-3 years of experience).
        - Return FALSE if: The title includes "Senior," "Lead," "Principal," "Director," or if the text requires 4+ years of experience.
        - Return TRUE if: The title includes "Junior," "Associate," "Entry-level," "Trainee," "Intern," "Internship", or if the experience requirement is 0-3 years (or not mentioned).

        5. requires_phd: (true/false)
        - Return TRUE only if a PhD or Doctorate is explicitly listed as a MANDATORY requirement. (If it is "preferred," return false).


        ### OUTPUT FORMAT
        Respond ONLY with valid JSON.
        {{
            "keyword_match": boolean,
            "visa_sponsorship": boolean,
            "entry_level": boolean,
            "requires_phd": boolean,
            "is_internship": boolean,
            "reason": "Identify the specific Target Role that matched and the years of experience found."
        }}
        """

    return prompt


def _parse_response(response_text: str) -> Dict:
    """Parse LLM response into structured result"""
    try:
        # Try to find JSON in response
        start = response_text.find('{')
        end = response_text.rfind('}') + 1

        if start >= 0 and end > start:
            json_str = response_text[start:end]
            result = json.loads(json_str)

            # Ensure all required fields exist
            return {
                "keyword_match": result.get("keyword_match", True),
                "visa_sponsorship": result.get("visa_sponsorship", True),
                "entry_level": result.get("entry_level", True),
                "requires_phd": result.get("requires_phd", False),
                "is_internship": result.get("is_internship", False),
                "reason": result.get("reason", "")
            }
        else:
            # Fallback parsing
            response_lower = response_text.lower()
            return {
                "keyword_match": "keyword_match\": true" in response_lower or "keyword_match\":true" in response_lower,
                "visa_sponsorship": "visa_sponsorship\": true" in response_lower or "no sponsor" not in response_lower,
                "entry_level": "entry_level\": true" in response_lower,
                "requires_phd": "requires_phd\": true" in response_lower,
                "is_internship": "is_internship\": true" in response_lower,
                "reason": "Parsed from text response"
            }

    except json.JSONDecodeError:
        # Default to permissive on parse error
        return {
            "keyword_match": True,
            "visa_sponsorship": True,
            "entry_level": True,
            "requires_phd": False,
            "is_internship": False,
            "reason": "JSON parse error - defaulting to pass"
        }


async def _call_openrouter(
    messages: List[Dict[str, str]],
    model: str = OPENROUTER_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 8192,
    client: Optional[AsyncOpenAI] = None,
    job_context: Optional[str] = None,
) -> str:
    """
    Make an async call to OpenRouter API using AsyncOpenAI client.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.
        model: OpenRouter model identifier.
        temperature: Sampling temperature (0-1).
        max_tokens: Maximum tokens in response.
        client: Optional AsyncOpenAI client for connection reuse.
        job_context: Optional job identifier for logging (e.g., "Job Title @ Company").

    Returns:
        The assistant's response content.

    Raises:
        OpenRouterError: If the API call fails.
    """
    if client is None:
        client = _get_openrouter_client()

    # Log the prompt being sent
    context_str = f" [{job_context}]" if job_context else ""
    user_prompt = next((m['content'] for m in messages if m['role'] == 'user'), '')
    logger.debug(f"LLM_PROMPT{context_str}:\n{'-'*60}\n{user_prompt}\n{'-'*60}")

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        response_content = response.choices[0].message.content

        # Log the response received
        logger.debug(f"LLM_RESPONSE{context_str}:\n{'-'*60}\n{response_content}\n{'-'*60}")

        return response_content

    except Exception as e:
        error_str = str(e)
        logger.error(f"OpenRouter API error{context_str}: {error_str}")
        # Check for rate limiting (429)
        if "429" in error_str or "rate" in error_str.lower():
            raise OpenRouterError("Rate limited (429)") from e
        raise OpenRouterError(f"API request failed: {error_str}") from e


async def evaluate_job_async(
    job: Dict,
    search_terms: List[str],
    client: Optional[AsyncOpenAI] = None,
) -> Dict:
    """
    Evaluate a single job using OpenRouter API asynchronously.

    Args:
        job: Job dictionary with title, company, location, description
        search_terms: List of target job roles
        client: Optional AsyncOpenAI client for connection reuse

    Returns:
        Evaluation result with pass/fail and reasons
    """
    job_title = job.get('title', 'Unknown')
    company = job.get('company', 'Unknown')
    job_context = f"{job_title} @ {company}"

    try:
        # Skip jobs with no description
        desc = _safe_str(job.get('description'), '')
        if not desc or len(desc) < 50:
            logger.debug(f"SKIPPED [{job_context}]: No description (length={len(desc)})")
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

        prompt = _create_prompt(job, search_terms)

        messages = [
            {"role": "system", "content": "You are an expert Recruitment Consultant and Talent Acquisition Specialist across all industries. You specialize in mapping job titles to standardized job families, understanding that different companies use different nomenclature for the same professional role."},
            {"role": "user", "content": prompt}
        ]

        response_text = await _call_openrouter(messages, client=client, job_context=job_context)
        result = _parse_response(response_text)
        result['job_title'] = job_title
        result['company'] = company

        # Log the evaluation result
        logger.info(
            f"EVALUATED [{job_context}]: "
            f"keyword={result.get('keyword_match')}, "
            f"visa={result.get('visa_sponsorship')}, "
            f"entry={result.get('entry_level')}, "
            f"phd={result.get('requires_phd')}, "
            f"intern={result.get('is_internship')} | "
            f"{result.get('reason', '')[:80]}"
        )

        return result

    except OpenRouterError as e:
        logger.warning(f"OpenRouter error [{job_context}]: {e}")
        # On rate limit (429), filter out the job
        if "429" in str(e) or "Rate limited" in str(e):
            logger.warning(f"Rate limited - filtering out job [{job_context}]")
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
        # Default to pass on other errors
        return {
            "keyword_match": True,
            "visa_sponsorship": True,
            "entry_level": True,
            "requires_phd": False,
            "is_internship": False,
            "reason": f"API error: {str(e)[:50]}",
            "error": True,
            "job_title": job_title,
            "company": company,
        }
    except Exception as e:
        logger.error(f"Unexpected error evaluating job [{job_context}]: {e}", exc_info=True)
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


def should_include_job(evaluation: Dict) -> bool:
    """
    Determine if job should be included based on evaluation.

    Note: visa_sponsorship is NOT filtered here - it's recorded in llm_evaluation
    for per-recipient filtering later. Recipients with needs_sponsorship=True
    will have jobs filtered by visa_sponsorship in email_sender.
    """
    return (
        evaluation.get("keyword_match", False) and
        # visa_sponsorship removed - tracked but not filtered globally
        evaluation.get("entry_level", False) and
        not evaluation.get("requires_phd", True) and
        not evaluation.get("is_internship", True)
    )


class OpenRouterLLMFilter:
    """Filter jobs using OpenRouter API with async inference"""

    def __init__(self, model: str = OPENROUTER_MODEL, concurrency: int = 20, rate_limit_delay: float = 60):
        """
        Initialize the OpenRouter LLM filter.

        Args:
            model: OpenRouter model identifier
            concurrency: Maximum concurrent API calls
            rate_limit_delay: Delay between requests in seconds (auto-set for free models)
        """
        self.model = model
        # Auto-detect free model and apply rate limiting (20 req/min limit, target 19/min = 3.16s delay)
        self.is_free_model = ":free" in model.lower()
        # if self.is_free_model:
        #     self.concurrency = 1  # Force sequential for free models
        #     self.rate_limit_delay = rate_limit_delay if rate_limit_delay > 0 else 3.2
        # else:
        self.concurrency = concurrency
        self.rate_limit_delay = rate_limit_delay

        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY environment variable not set")

        logger.info("🤖 OpenRouter LLM Filter initialized")
        logger.info(f"   Model: {self.model}")
        logger.info(f"   Concurrency: {self.concurrency}")
        if self.is_free_model:
            logger.warning("   ⚠️  Free model detected - rate limited (~19 req/min)")

    async def evaluate_job(
        self,
        job: Dict,
        search_terms: List[str],
        client: Optional[AsyncOpenAI] = None,
    ) -> Dict:
        """Evaluate a single job asynchronously."""
        return await evaluate_job_async(job, search_terms, client)

    async def filter_jobs_async(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        verbose: bool = True,
    ) -> List[Dict]:
        """
        Filter jobs using OpenRouter API with async concurrent calls.

        Args:
            jobs_list: List of job dictionaries
            search_terms: Target job roles to match
            verbose: Print progress

        Returns:
            Filtered list of jobs that pass all criteria
        """
        total = len(jobs_list)
        if total == 0:
            return []

        logger.info(f"   🚀 Starting async filtering with concurrency={self.concurrency}...")
        logger.info(f"   📊 Processing {total} jobs...")

        results = []
        completed = 0
        # Use a single client for all requests (connection pooling)
        client = _get_openrouter_client()
        for batch_idx in range(0, total, self.concurrency):
            jobs = jobs_list[batch_idx: batch_idx + self.concurrency]

            async with asyncio.TaskGroup() as tg:
                tasks = [(job, tg.create_task(self.evaluate_job(job, search_terms, client))) for job in jobs]
            # wait for rate limiting
            await asyncio.sleep(self.rate_limit_delay)
            results += [(job, task_future.result()) for job, task_future in tasks]
            completed += self.concurrency

            if verbose:
                logger.info(f"   🤖 Evaluated {min(completed, total)}/{total}...")
            batch_idx += self.concurrency


        # Process results
        filtered = []
        excluded_keyword = 0
        excluded_experience = 0
        excluded_phd = 0
        excluded_internship = 0
        skipped = 0
        error = 0
        no_visa_count = 0  # Track for stats, but don't filter

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

            # Track visa sponsorship status but don't filter
            # (filtering happens per-recipient in email_sender)
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

            # Job passed all filters
            job['llm_evaluation'] = evaluation
            filtered.append(job)

        logger.info(f"   Skipped {error} errored jobs (error calling OpenRouter)")
        logger.info(f"   Skipped {skipped} jobs (no description)")
        logger.info(f"   Excluded {excluded_keyword} jobs (keyword mismatch)")
        logger.info(f"   Excluded {excluded_experience} jobs (not entry-level)")
        logger.info(f"   Excluded {excluded_phd} jobs (PhD required)")
        logger.info(f"   Excluded {excluded_internship} jobs (internship)")
        logger.info(f"   Tracked {no_visa_count} jobs without visa sponsorship (not filtered)")
        logger.info(f"   ✅ {len(filtered)} jobs passed LLM filter (async)")

        return filtered

    def filter_jobs(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        verbose: bool = True,
    ) -> List[Dict]:
        """
        Synchronous wrapper for filter_jobs_async.

        Args:
            jobs_list: List of job dictionaries
            search_terms: Target job roles to match
            verbose: Print progress

        Returns:
            Filtered list of jobs that pass all criteria
        """
        return asyncio.run(self.filter_jobs_async(jobs_list, search_terms, verbose))

    # Alias for backwards compatibility with old LocalLLMFilter interface
    def filter_jobs_parallel(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        num_workers: int = 0,
        verbose: bool = True,
    ) -> List[Dict]:
        """
        Backwards-compatible method that uses async filtering.

        Note: num_workers is ignored, concurrency is controlled by self.concurrency
        """
        if num_workers > 0:
            logger.warning(f"   ⚠️ num_workers={num_workers} ignored, using async concurrency={self.concurrency}")
        return self.filter_jobs(jobs_list, search_terms, verbose)


# Convenience function for simple usage
async def filter_jobs_async(
    jobs_list: List[Dict],
    search_terms: List[str],
    concurrency: int = 10,
    verbose: bool = True,
) -> List[Dict]:
    """
    Filter jobs using OpenRouter API with async concurrent calls.

    Args:
        jobs_list: List of job dictionaries
        search_terms: Target job roles to match
        concurrency: Maximum concurrent API calls
        verbose: Print progress

    Returns:
        Filtered list of jobs that pass all criteria
    """
    filter_instance = OpenRouterLLMFilter(concurrency=concurrency)
    return await filter_instance.filter_jobs_async(jobs_list, search_terms, verbose)


def filter_jobs(
    jobs_list: List[Dict],
    search_terms: List[str],
    concurrency: int = 10,
    verbose: bool = True,
) -> List[Dict]:
    """
    Synchronous wrapper for filter_jobs_async.

    Args:
        jobs_list: List of job dictionaries
        search_terms: Target job roles to match
        concurrency: Maximum concurrent API calls
        verbose: Print progress

    Returns:
        Filtered list of jobs that pass all criteria
    """
    return asyncio.run(filter_jobs_async(jobs_list, search_terms, concurrency, verbose))


async def main_async():
    """Test the async LLM filter"""
    test_job = {
        "title": "Junior Data Analyst",
        "company": "Google",
        "location": "San Francisco, CA",
        "description": """
        We are looking for a Junior Data Analyst to join our team.

        Requirements:
        - Bachelor's degree in Statistics, Mathematics, or related field
        - 0-2 years of experience
        - Proficiency in SQL and Python

        We offer H1B visa sponsorship for qualified candidates.
        """
    }

    search_terms = ["data analyst", "product manager", "data scientist"]

    logger.info("🧪 Testing OpenRouter LLM Filter...")

    result = await evaluate_job_async(test_job, search_terms)
    logger.info("📊 Evaluation Result:")
    logger.info(json.dumps(result, indent=2))

    logger.info(f"✅ Should include: {should_include_job(result)}")


def main():
    """Test the LLM filter (sync wrapper)"""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()


# =============================================================================
# OLD LOCAL INFERENCE LOGIC (PRESERVED - DO NOT DELETE)
# =============================================================================
# The following code is the original implementation using local LLM inference
# with llama_cpp and huggingface_hub. It is preserved here for reference and
# as a fallback option if needed.
#
# To use the old local inference:
# 1. Uncomment the code below
# 2. Install dependencies: pip install huggingface_hub llama-cpp-python
# 3. Use LocalLLMFilter instead of OpenRouterLLMFilter
# =============================================================================

"""
# OLD IMPORTS (for local inference)
# from pathlib import Path
# from huggingface_hub import hf_hub_download
# from llama_cpp import Llama
# import multiprocessing as mp
# from functools import partial
# import psutil

# Global worker state (initialized per process)
_worker_llm: Optional[Llama] = None
_worker_model_path: Optional[str] = None


def _init_worker(model_path: str, n_ctx: int, n_threads: int) -> None:
    '''Initialize LLM model in worker process'''
    global _worker_llm, _worker_model_path
    _worker_model_path = model_path
    logger.info(f"🔧 Worker {mp.current_process().name} loading model...")
    _worker_llm = Llama(
        model_path=model_path,
        n_ctx=n_ctx,
        n_threads=n_threads,
        n_batch=512,
        verbose=False
    )
    logger.info(f"✅ Worker {mp.current_process().name} ready")


def _safe_str_worker(value, default: str = '') -> str:
    '''Safely convert value to string, handling NaN/None (worker version)'''
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return str(value)


def _create_prompt_worker(job: Dict, search_terms: List[str]) -> str:
    '''Create prompt for job evaluation (worker version)'''
    title = _safe_str_worker(job.get('title'), 'Unknown')
    company = _safe_str_worker(job.get('company'), 'Unknown')
    location = _safe_str_worker(job.get('location'), 'Unknown')
    description = _safe_str_worker(job.get('description'), '')

    search_terms_str = ", ".join(search_terms)

    prompt = f\"\"\"Analyze this job posting and answer with JSON only.

Job Title: {title}
Company: {company}
Location: {location}
Description: {description}

Target Roles: {search_terms_str}

Evaluate:
1. keyword_match: Does the job title/description match any target roles? (true/false)
2. visa_sponsorship: Does it mention H1B, visa sponsorship, or NOT explicitly reject sponsorship? (true/false)
3. entry_level: Is this entry-level (0-1 years experience required or doesn't mention experience at all)? Check for "entry", "junior", "associate", "new grad", or the required years of experience is less than/equal to 1.(true/false)
4. requires_phd: Does it require a PhD or doctorate? (true/false)
5. is_internship: Is this an internship position? Look for keywords like "intern", "internship", "co-op", or "summer program". (true/false)

Respond ONLY with valid JSON:
{{"keyword_match": true/false, "visa_sponsorship": true/false, "entry_level": true/false, "requires_phd": true/false, "is_internship": true/false, "reason": "brief explanation"}}\"\"\"

    return prompt


def _parse_response_worker(response_text: str) -> Dict:
    '''Parse LLM response into structured result (worker version)'''
    try:
        start = response_text.find('{')
        end = response_text.rfind('}') + 1

        if start >= 0 and end > start:
            json_str = response_text[start:end]
            result = json.loads(json_str)

            return {
                "keyword_match": result.get("keyword_match", True),
                "visa_sponsorship": result.get("visa_sponsorship", True),
                "entry_level": result.get("entry_level", True),
                "requires_phd": result.get("requires_phd", False),
                "is_internship": result.get("is_internship", False),
                "reason": result.get("reason", "")
            }
        else:
            response_lower = response_text.lower()
            return {
                "keyword_match": "keyword_match\\": true" in response_lower,
                "visa_sponsorship": "visa_sponsorship\\": true" in response_lower,
                "entry_level": "entry_level\\": true" in response_lower,
                "requires_phd": "requires_phd\\": true" in response_lower,
                "is_internship": "is_internship\\": true" in response_lower,
                "reason": "Parsed from text response"
            }

    except json.JSONDecodeError:
        return {
            "keyword_match": True,
            "visa_sponsorship": True,
            "entry_level": True,
            "requires_phd": False,
            "is_internship": False,
            "reason": "JSON parse error - defaulting to pass"
        }


def _evaluate_job_worker(args: Tuple[Dict, List[str]]) -> Dict:
    '''
    Evaluate a single job using the worker's LLM instance.

    Args:
        args: Tuple of (job dict, search_terms list)

    Returns:
        Evaluation result dict with '_job' key containing original job
    '''
    global _worker_llm
    job, search_terms = args

    try:
        desc = _safe_str_worker(job.get('description'), '')
        if not desc or len(desc) < 50:
            return {
                "keyword_match": False,
                "visa_sponsorship": False,
                "entry_level": False,
                "requires_phd": False,
                "is_internship": False,
                "reason": "No description available - skipped",
                "skipped": True,
                "job_title": job.get('title', 'Unknown'),
                "company": job.get('company', 'Unknown'),
                "_job": job
            }

        prompt = _create_prompt_worker(job, search_terms)

        _worker_llm.reset()

        messages = [
            {"role": "system", "content": "You are a job posting analyzer. Respond only with valid JSON."},
            {"role": "user", "content": prompt}
        ]

        response = _worker_llm.create_chat_completion(
            messages=messages,
            max_tokens=256,
            temperature=0.1,
        )

        response_text = response['choices'][0]['message']['content'].strip()
        result = _parse_response_worker(response_text)
        result['job_title'] = job.get('title', 'Unknown')
        result['company'] = job.get('company', 'Unknown')
        result['_job'] = job

        return result

    except Exception as e:
        return {
            "keyword_match": True,
            "visa_sponsorship": True,
            "entry_level": True,
            "requires_phd": False,
            "is_internship": False,
            "reason": f"LLM error: {str(e)[:50]}",
            "error": True,
            "job_title": job.get('title', 'Unknown'),
            "company": job.get('company', 'Unknown'),
            "_job": job
        }


class LocalLLMFilter:
    '''Filter jobs using local LLM inference'''

    MODEL_REPO = "LiquidAI/LFM2.5-1.2B-Instruct-GGUF"
    MODEL_FILE = "LFM2.5-1.2B-Instruct-Q8_0.gguf"

    def __init__(self, model_dir: str = "models"):
        '''
        Initialize the local LLM filter

        Args:
            model_dir: Directory to store downloaded models
        '''
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)
        self.model_path = self.model_dir / self.MODEL_FILE
        self.llm = None

        # Download model if not exists
        if not self.model_path.exists():
            logger.info(f"📥 Downloading model {self.MODEL_FILE}...")
            self._download_model()

        # Load model
        logger.info(f"🤖 Loading LLM model...")
        self._load_model()
        logger.info(f"✅ LLM model loaded successfully")

    def _download_model(self):
        '''Download the GGUF model from HuggingFace'''
        try:
            downloaded_path = hf_hub_download(
                repo_id=self.MODEL_REPO,
                filename=self.MODEL_FILE,
                local_dir=str(self.model_dir)
            )
            logger.info(f"✅ Model downloaded to {downloaded_path}")
        except Exception as e:
            logger.error(f"❌ Failed to download model: {e}")
            raise

    def _load_model(self):
        '''Load the GGUF model with llama.cpp'''
        try:
            # Use a reasonable context size that fits in memory
            # The model supports 128K but we'll use 8K to be safe
            n_ctx = 8192

            logger.info(f"📊 Loading model with n_ctx={n_ctx}...")

            self.llm = Llama(
                model_path=str(self.model_path),
                n_ctx=n_ctx,
                n_threads=8,  # Use more CPU threads
                n_batch=512,  # Batch size for prompt processing
                verbose=True
            )
            logger.info(f"✅ Model loaded successfully (context: {n_ctx} tokens)")
        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")
            raise

    def _safe_str(self, value, default: str = '') -> str:
        '''Safely convert value to string, handling NaN/None'''
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return str(value)

    def _create_prompt(self, job: Dict, search_terms: List[str]) -> str:
        '''Create prompt for job evaluation'''
        title = self._safe_str(job.get('title'), 'Unknown')
        company = self._safe_str(job.get('company'), 'Unknown')
        location = self._safe_str(job.get('location'), 'Unknown')
        description = self._safe_str(job.get('description'), '')
        search_terms_str = ", ".join(search_terms)

        prompt = f\"\"\"Analyze this job posting and answer with JSON only.

Job Title: {title}
Company: {company}
Location: {location}
Description: {description}

Target Roles: {search_terms_str}

Evaluate:
1. keyword_match: Does the job title/description match any target roles? That is, does one of the target roles, which are separated by a comma, exist in the job title/description? (true/false)
2. visa_sponsorship: Does it mention H1B, visa sponsorship, or NOT explicitly reject sponsorship? (true/false)
3. entry_level: Is this entry-level (0-3 years experience required)? keywords including "entry", "junior", "associate", "new grad", or "0-3 years of experience" should be true. keywords like
    senior, mid-level, Sr., staff, principal should be considered false. (true/false)
4. requires_phd: Does it require a PhD or doctorate? (true/false)
5. is_internship: Is this an internship position? Look for keywords like "intern", "internship", "co-op", or "summer program". (true/false)

Respond ONLY with valid JSON:
{{"keyword_match": true/false, "visa_sponsorship": true/false, "entry_level": true/false, "requires_phd": true/false, "is_internship": true/false, "reason": "brief explanation"}}\"\"\"

        return prompt

    def evaluate_job(self, job: Dict, search_terms: List[str], _retry: bool = True) -> Dict:
        '''
        Evaluate a single job using local LLM

        Args:
            job: Job dictionary
            search_terms: List of target job roles
            _retry: Internal flag for retry with truncation

        Returns:
            Evaluation result with pass/fail and reasons
        '''
        try:
            # Skip jobs with no description - can't evaluate them properly
            desc = self._safe_str(job.get('description'), '')
            if not desc or len(desc) < 50:
                logger.debug(f"⏭️ Skipping {job.get('title', 'Unknown')[:40]} - no/short description ({len(desc)} chars)")
                return {
                    "keyword_match": False,
                    "visa_sponsorship": False,
                    "entry_level": False,
                    "requires_phd": False,
                    "is_internship": False,
                    "reason": "No description available - skipped",
                    "skipped": True
                }

            prompt = self._create_prompt(job, search_terms)

            # Debug: print prompt stats
            prompt_len = len(prompt)
            logger.debug(f"📝 Job: {job.get('title', 'Unknown')[:40]} | Prompt: {prompt_len} chars | Desc: {len(desc)} chars")

            # Reset KV cache to avoid state corruption between requests
            self.llm.reset()

            # Use chat completion format for this instruction-tuned model
            messages = [
                {"role": "system", "content": "You are a job posting analyzer. Respond only with valid JSON."},
                {"role": "user", "content": prompt}
            ]

            response = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=256,
                temperature=0.1,
            )

            response_text = response['choices'][0]['message']['content'].strip()
            finish_reason = response['choices'][0].get('finish_reason', 'unknown')
            logger.debug(f"✅ Response: {len(response_text)} chars, finish: {finish_reason}")
            if response_text:
                logger.debug(f"📄 Raw response: {response_text[:200]}...")

            # Parse JSON from response
            result = self._parse_response(response_text)
            result['job_title'] = job.get('title', 'Unknown')
            result['company'] = job.get('company', 'Unknown')

            return result

        except Exception as e:
            import traceback
            error_msg = str(e)
            desc = self._safe_str(job.get('description'), '')
            prompt = self._create_prompt(job, search_terms)

            # Debug: log detailed error info
            logger.error(f"❌ ERROR for {job.get('title', 'Unknown')[:40]}")
            logger.error(f"   Error type: {type(e).__name__}")
            logger.error(f"   Error msg: {error_msg}")
            logger.debug(f"   Prompt length: {len(prompt)} chars")
            logger.debug(f"   Description length: {len(desc)} chars")
            logger.debug(f"   Full traceback: {traceback.format_exc()}")

            # Estimate token count (rough: ~4 chars per token)
            estimated_tokens = len(prompt) // 4
            logger.debug(f"   Estimated tokens: ~{estimated_tokens}")
            logger.debug(f"   Model n_ctx: {self.llm.n_ctx()}")

            # If context overflow, retry with truncated description
            if "llama_decode returned -1" in error_msg and _retry:
                # Try with much shorter description
                if len(desc) > 1500:
                    logger.warning(f"   🔄 Retrying with truncated description (1500 chars)...")
                    truncated_job = job.copy()
                    truncated_job['description'] = desc[:1500] + "..."
                    return self.evaluate_job(truncated_job, search_terms, _retry=False)

            logger.warning(f"⚠️ LLM evaluation error for {job.get('title', 'Unknown')}: {e}")
            # Default to pass on error (let rule-based filter handle it)
            return {
                "keyword_match": True,
                "visa_sponsorship": True,
                "entry_level": True,
                "requires_phd": False,
                "is_internship": False,
                "reason": f"LLM error: {str(e)[:50]}",
                "error": True
            }

    def _parse_response(self, response_text: str) -> Dict:
        '''Parse LLM response into structured result'''
        try:
            # Try to find JSON in response
            start = response_text.find('{')
            end = response_text.rfind('}') + 1

            if start >= 0 and end > start:
                json_str = response_text[start:end]
                result = json.loads(json_str)

                # Ensure all required fields exist
                return {
                    "keyword_match": result.get("keyword_match", True),
                    "visa_sponsorship": result.get("visa_sponsorship", True),
                    "entry_level": result.get("entry_level", True),
                    "requires_phd": result.get("requires_phd", False),
                    "is_internship": result.get("is_internship", False),
                    "reason": result.get("reason", "")
                }
            else:
                # Fallback parsing
                response_lower = response_text.lower()
                return {
                    "keyword_match": "keyword_match\\": true" in response_lower or "keyword_match\\":true" in response_lower,
                    "visa_sponsorship": "visa_sponsorship\\": true" in response_lower or "no sponsor" not in response_lower,
                    "entry_level": "entry_level\\": true" in response_lower,
                    "requires_phd": "requires_phd\\": true" in response_lower,
                    "is_internship": "is_internship\\": true" in response_lower,
                    "reason": "Parsed from text response"
                }

        except json.JSONDecodeError:
            # Default to permissive on parse error
            return {
                "keyword_match": True,
                "visa_sponsorship": True,
                "entry_level": True,
                "requires_phd": False,
                "is_internship": False,
                "reason": "JSON parse error - defaulting to pass"
            }

    def should_include_job(self, evaluation: Dict) -> bool:
        '''Determine if job should be included based on evaluation'''
        return (
            evaluation.get("keyword_match", False) and
            evaluation.get("visa_sponsorship", False) and
            evaluation.get("entry_level", False) and
            not evaluation.get("requires_phd", True) and
            not evaluation.get("is_internship", True)
        )

    def filter_jobs(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        verbose: bool = True
    ) -> List[Dict]:
        '''
        Filter jobs using local LLM

        Args:
            jobs_list: List of job dictionaries
            search_terms: Target job roles to match
            verbose: Print progress

        Returns:
            Filtered list of jobs that pass all criteria
        '''
        filtered = []
        excluded_keyword = 0
        excluded_visa = 0
        excluded_experience = 0
        excluded_phd = 0
        excluded_internship = 0
        skipped = 0

        total = len(jobs_list)

        for i, job in enumerate(jobs_list, 1):
            if verbose and i % 10 == 0:
                logger.info(f"🤖 Evaluating {i}/{total}...")

            evaluation = self.evaluate_job(job, search_terms)

            # Track skipped jobs (no description)
            if evaluation.get("skipped", False):
                skipped += 1
                continue

            if not evaluation.get("keyword_match", False):
                excluded_keyword += 1
                continue

            if not evaluation.get("visa_sponsorship", False):
                excluded_visa += 1
                continue

            if not evaluation.get("entry_level", False):
                excluded_experience += 1
                continue

            if evaluation.get("requires_phd", False):
                excluded_phd += 1
                continue

            if evaluation.get("is_internship", False):
                excluded_internship += 1
                continue

            # Job passed all filters
            job['llm_evaluation'] = evaluation
            filtered.append(job)

        logger.info(f"Skipped {skipped} jobs (no description)")
        logger.info(f"Excluded {excluded_keyword} jobs (keyword mismatch)")
        logger.info(f"Excluded {excluded_visa} jobs (no visa sponsorship)")
        logger.info(f"Excluded {excluded_experience} jobs (not entry-level)")
        logger.info(f"Excluded {excluded_phd} jobs (PhD required)")
        logger.info(f"Excluded {excluded_internship} jobs (internship)")
        logger.info(f"✅ {len(filtered)} jobs passed LLM filter")

        return filtered

    def _calculate_optimal_workers(self, requested_workers: int) -> int:
        '''
        Calculate optimal number of workers based on available system RAM.

        Each model instance uses approximately 1.5-2GB RAM for this 1.2B model.
        We reserve 2GB for system overhead and other processes.

        Args:
            requested_workers: User-requested number of workers

        Returns:
            Optimal number of workers based on available RAM
        '''
        try:
            mem = psutil.virtual_memory()
            available_gb = mem.available / (1024 ** 3)
            total_gb = mem.total / (1024 ** 3)

            # Each worker needs ~2GB (model + overhead), reserve 2GB for system
            ram_per_worker = 2.0
            system_reserve = 2.0

            usable_ram = available_gb - system_reserve
            max_workers_by_ram = max(1, int(usable_ram / ram_per_worker))

            # Also limit by CPU cores
            max_workers_by_cpu = max(1, mp.cpu_count() // 2)

            optimal = min(requested_workers, max_workers_by_ram, max_workers_by_cpu)

            logger.info(f"💾 RAM: {available_gb:.1f}GB available / {total_gb:.1f}GB total")
            logger.debug(f"🔢 Workers: requested={requested_workers}, max_by_ram={max_workers_by_ram}, max_by_cpu={max_workers_by_cpu}")
            logger.info(f"✅ Using {optimal} worker(s)")

            return optimal

        except Exception as e:
            logger.warning(f"⚠️ Could not detect RAM: {e}, using 1 worker")
            return 1

    def filter_jobs_parallel(
        self,
        jobs_list: List[Dict],
        search_terms: List[str],
        num_workers: int = 0,
        verbose: bool = True
    ) -> List[Dict]:
        '''
        Filter jobs using multiple LLM instances in parallel.

        Each worker process loads its own model instance for true parallelism.

        Args:
            jobs_list: List of job dictionaries
            search_terms: Target job roles to match
            num_workers: Number of workers (0 = auto-detect based on RAM)
            verbose: Print progress

        Returns:
            Filtered list of jobs that pass all criteria
        '''
        total = len(jobs_list)
        if total == 0:
            return []

        # Auto-detect or validate worker count based on system RAM
        if num_workers <= 0:
            num_workers = self._calculate_optimal_workers(4)  # Default max 4
        else:
            num_workers = self._calculate_optimal_workers(num_workers)

        # For small job lists or single worker, use sequential processing
        if total < num_workers * 2 or num_workers == 1:
            logger.info(f"📝 Using sequential processing (jobs={total}, workers={num_workers})...")
            return self.filter_jobs(jobs_list, search_terms, verbose)

        logger.info(f"🚀 Starting parallel processing with {num_workers} workers...")
        logger.info(f"📊 Processing {total} jobs...")

        # Prepare args for workers: list of (job, search_terms) tuples
        work_items = [(job, search_terms) for job in jobs_list]

        # Calculate threads per worker (divide available threads)
        total_threads = 8
        threads_per_worker = max(2, total_threads // num_workers)

        # Create process pool with model initialization
        try:
            with mp.Pool(
                processes=num_workers,
                initializer=_init_worker,
                initargs=(str(self.model_path), 8192, threads_per_worker)
            ) as pool:
                # Process jobs in parallel
                results = pool.map(_evaluate_job_worker, work_items)
        except Exception as e:
            logger.error(f"❌ Parallel processing failed: {e}")
            logger.info(f"🔄 Falling back to sequential processing...")
            return self.filter_jobs(jobs_list, search_terms, verbose)

        # Process results
        filtered = []
        excluded_keyword = 0
        excluded_visa = 0
        excluded_experience = 0
        excluded_phd = 0
        excluded_internship = 0
        skipped = 0

        for evaluation in results:
            job = evaluation.pop('_job', None)
            if job is None:
                continue

            if evaluation.get("skipped", False):
                skipped += 1
                continue

            if not evaluation.get("keyword_match", False):
                excluded_keyword += 1
                continue

            if not evaluation.get("visa_sponsorship", False):
                excluded_visa += 1
                continue

            if not evaluation.get("entry_level", False):
                excluded_experience += 1
                continue

            if evaluation.get("requires_phd", False):
                excluded_phd += 1
                continue

            if evaluation.get("is_internship", False):
                excluded_internship += 1
                continue

            job['llm_evaluation'] = evaluation
            filtered.append(job)

        logger.info(f"Skipped {skipped} jobs (no description)")
        logger.info(f"Excluded {excluded_keyword} jobs (keyword mismatch)")
        logger.info(f"Excluded {excluded_visa} jobs (no visa sponsorship)")
        logger.info(f"Excluded {excluded_experience} jobs (not entry-level)")
        logger.info(f"Excluded {excluded_phd} jobs (PhD required)")
        logger.info(f"Excluded {excluded_internship} jobs (internship)")
        logger.info(f"✅ {len(filtered)} jobs passed LLM filter (parallel)")

        return filtered
"""
