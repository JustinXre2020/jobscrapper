"""
Centralised configuration for Job Hunter Sentinel.

All environment variables are declared once in ``Settings`` (pydantic-settings).
The module-level ``settings`` singleton is the single source of truth — every
other module should import from here instead of calling ``os.getenv`` directly.

Usage:

    from utils.config import settings

    print(settings.hours_old)          # typed int, default 24
    print(settings.gmail_email)        # Optional[str]
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from infra.logging_config import configure_logging

# Resolve .env relative to this file so it's always found regardless of cwd
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


# ---------------------------------------------------------------------------
# Settings — every env var the application reads, with types and defaults
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file.

    pydantic-settings maps ``UPPER_CASE`` env vars to ``lower_case`` fields
    automatically, so ``GMAIL_EMAIL`` → ``settings.gmail_email``.
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",          # silently ignore unknown env vars
        case_sensitive=False,
    )

    # --- Email ---------------------------------------------------------------
    gmail_email: Optional[str] = None
    gmail_app_password: Optional[str] = None

    # --- Recipients ----------------------------------------------------------
    #: JSON array string: '[{"email":…, "needs_sponsorship":…, "search_terms":[…]}]'
    recipients: Optional[str] = None
    results_wanted: int = 10
    #: JSON object mapping search term → results count, e.g. '{"data analyst": 20}'
    results_wanted_map: str = "{}"

    # --- Scraping ------------------------------------------------------------
    #: Comma-separated job board names, e.g. "indeed,linkedin"
    sites: str = "indeed"
    #: Comma-separated locations, e.g. "San Francisco, CA,New York, NY"
    locations: str = "San Francisco, CA"
    #: Only return jobs posted within this many hours
    hours_old: int = 24

    # --- LLM: OpenRouter -----------------------------------------------------
    openrouter_api_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    openrouter_model: str = "liquid/lfm-2.5-1.2b-thinking:free"

    # --- LLM: Local inference (Ollama / llama.cpp / etc.) --------------------
    local_llm_api_url: str = "http://localhost:11434/v1"
    #: API key sent to the local server (most servers accept any non-empty value)
    local_llm_api_key: str = "local"
    local_llm_model: str = "liquid/lfm-2.5-1.2b-thinking"

    # --- Redis ---------------------------------------------------------------
    redis_host: Optional[str] = None
    redis_port: Optional[int] = None

    # --- Per-node model routing ----------------------------------------------
    summarizer_provider: str = "local"
    summarizer_model: Optional[str] = None   # None → use provider default
    analyzer_provider: str = "openrouter"
    analyzer_model: str = "liquid/lfm-2.2-6b"

    # --- Workflow ------------------------------------------------------------
    #: Max concurrent jobs processed in a single LLM batch
    agent_concurrency: int = 50

    # --- Computed helpers (not env vars) ------------------------------------

    @field_validator("results_wanted_map", mode="before")
    @classmethod
    def _coerce_results_wanted_map(cls, v: str) -> str:
        """Accept the raw JSON string as-is; parse errors handled later."""
        return v or "{}"


#: Singleton — import this in all consumer modules.
settings = Settings()


# ---------------------------------------------------------------------------
# Search-term group configuration (static, not from env)
# ---------------------------------------------------------------------------

# Combined search term groups: group name -> list of queries to scrape.
# "business analyst/data analyst" scrapes for both terms and stores results
# under the group name for deduplication.
SEARCH_TERM_GROUPS: Dict[str, List[str]] = {
    "business analyst/data analyst": ["business analyst", "data analyst"],
}

# Reverse lookup: individual term -> group name (auto-built)
_TERM_TO_GROUP: Dict[str, str] = {}
for _group_name, _terms in SEARCH_TERM_GROUPS.items():
    for _term in _terms:
        _TERM_TO_GROUP[_term.lower().strip()] = _group_name

# Per-term scrape counts parsed from RESULTS_WANTED_MAP
DEFAULT_RESULTS_WANTED: int = settings.results_wanted

try:
    RESULTS_WANTED_MAP: Dict[str, int] = {
        k.lower().strip(): int(v)
        for k, v in json.loads(settings.results_wanted_map).items()
    }
except (json.JSONDecodeError, ValueError) as e:
    logger.warning(f"Invalid RESULTS_WANTED_MAP JSON, using empty map: {e}")
    RESULTS_WANTED_MAP = {}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def normalize_search_term(term: str) -> str:
    """Map individual terms to their group name if part of a group, else return as-is."""
    return _TERM_TO_GROUP.get(term.lower().strip(), term.strip())


def get_results_wanted(term: str) -> int:
    """Get the results_wanted count for a search term (or group)."""
    return RESULTS_WANTED_MAP.get(term.lower().strip(), DEFAULT_RESULTS_WANTED)


def get_scrape_queries(term: str) -> List[str]:
    """Get all scrape queries for a term. Groups expand to their member queries."""
    key = term.lower().strip()
    if key in SEARCH_TERM_GROUPS:
        return SEARCH_TERM_GROUPS[key]
    return [term]


def mask_email(email: str) -> str:
    """Mask email address for privacy in logs (e.g., j***n@gmail.com)."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


# ---------------------------------------------------------------------------
# Recipient dataclass + parsing
# ---------------------------------------------------------------------------

@dataclass
class Recipient:
    """Recipient configuration with search preferences."""
    email: str
    needs_sponsorship: bool
    search_terms: List[str]
    accepted_levels: List[str] = None  # default set in __post_init__

    def __post_init__(self):
        if self.accepted_levels is None:
            self.accepted_levels = ["entry"]


def parse_recipients() -> List[Recipient]:
    """Parse recipient configuration from environment variables.

    Priority:
    1. ``RECIPIENTS`` (JSON array) — new format with per-recipient search terms
    2. ``RECIPIENT_EMAIL`` (string) — legacy fallback with global SEARCH_TERMS

    Returns:
        List of Recipient objects.

    Raises:
        ValueError: If no valid recipient configuration found.
    """
    # Try new JSON format first
    if settings.recipients:
        try:
            recipients_data = json.loads(settings.recipients)
            recipients = []

            for r in recipients_data:
                email = r.get("email")
                if not email:
                    continue

                needs_sponsorship = r.get("needs_sponsorship", True)
                search_terms = r.get("search_terms", [])

                # Normalise search_terms to a list
                if isinstance(search_terms, str):
                    search_terms = [t.strip() for t in search_terms.split(",") if t.strip()]
                elif not isinstance(search_terms, list):
                    search_terms = []

                # Normalise group membership and deduplicate
                search_terms = list(dict.fromkeys(normalize_search_term(t) for t in search_terms))

                # Optional accepted job levels; default to ["entry"]
                accepted_levels = r.get("accepted_levels", ["entry"])
                if not isinstance(accepted_levels, list) or not accepted_levels:
                    accepted_levels = ["entry"]

                recipients.append(Recipient(
                    email=email,
                    needs_sponsorship=needs_sponsorship,
                    search_terms=search_terms,
                    accepted_levels=accepted_levels,
                ))

            logger.debug(f"{len(recipients)} recipient(s) loaded")
            for i, r in enumerate(recipients):
                logger.debug(
                    f"recipient[{i}] = email={mask_email(r.email)}, "
                    f"needs_sponsorship={r.needs_sponsorship}, "
                    f"search_terms={r.search_terms}, "
                    f"accepted_levels={r.accepted_levels}"
                )

            if recipients:
                logger.info(f"Loaded {len(recipients)} recipient(s) from RECIPIENTS config")
                return recipients

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid RECIPIENTS JSON: {e}")
            # Fall through to legacy format

    # Legacy fallback: single recipient with global search terms
    if not settings.recipient_email:
        raise ValueError(
            "No recipient configuration found. "
            "Set RECIPIENTS (JSON) or RECIPIENT_EMAIL environment variable."
        )

    search_terms = [t.strip() for t in settings.search_terms.split(",") if t.strip()]
    search_terms = list(dict.fromkeys(normalize_search_term(t) for t in search_terms))

    logger.info(
        f"Using legacy config: {mask_email(settings.recipient_email)} (needs_sponsorship=True)"
    )

    return [Recipient(
        email=settings.recipient_email,
        needs_sponsorship=True,  # Legacy default
        search_terms=search_terms,
    )]


def get_all_search_terms(recipients: List[Recipient]) -> List[str]:
    """Collect all unique search terms across all recipients.

    Returns:
        Deduplicated list of search terms (preserves first-occurrence order).
    """
    seen: set = set()
    unique_terms: List[str] = []

    for recipient in recipients:
        for term in recipient.search_terms:
            term_normalized = normalize_search_term(term)
            term_lower = term_normalized.lower()
            if term_lower and term_lower not in seen:
                seen.add(term_lower)
                unique_terms.append(term_normalized)

    return unique_terms

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
