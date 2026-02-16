"""
Recipient configuration for Job Hunter Sentinel
Supports multi-recipient with per-recipient search terms and sponsorship needs
"""
import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# --- Search Term Configuration ---

# Combined search term groups: group name -> list of queries to scrape
# "business analyst/data analyst" scrapes for both terms, results stored under the group name
SEARCH_TERM_GROUPS: Dict[str, List[str]] = {
    "business analyst/data analyst": ["business analyst", "data analyst"],
}

# Reverse lookup: individual term -> group name (auto-built)
_TERM_TO_GROUP: Dict[str, str] = {}
for _group_name, _terms in SEARCH_TERM_GROUPS.items():
    for _term in _terms:
        _TERM_TO_GROUP[_term.lower().strip()] = _group_name

# Per-term scrape counts (from env)
DEFAULT_RESULTS_WANTED: int = int(os.getenv("RESULTS_WANTED", "10"))

_results_map_json = os.getenv("RESULTS_WANTED_MAP", "{}")
try:
    RESULTS_WANTED_MAP: Dict[str, int] = {
        k.lower().strip(): int(v) for k, v in json.loads(_results_map_json).items()
    }
except (json.JSONDecodeError, ValueError) as e:
    logger.warning(f"Invalid RESULTS_WANTED_MAP JSON, using empty map: {e}")
    RESULTS_WANTED_MAP: Dict[str, int] = {}


def normalize_search_term(term: str) -> str:
    """Map individual terms to their group name if part of a group, otherwise return as-is."""
    return _TERM_TO_GROUP.get(term.lower().strip(), term.strip())


def get_results_wanted(term: str) -> int:
    """Get results_wanted count for a search term (or group)."""
    return RESULTS_WANTED_MAP.get(term.lower().strip(), DEFAULT_RESULTS_WANTED)


def get_scrape_queries(term: str) -> List[str]:
    """Get all scrape queries for a term. Groups expand to their member queries."""
    key = term.lower().strip()
    if key in SEARCH_TERM_GROUPS:
        return SEARCH_TERM_GROUPS[key]
    return [term]


def mask_email(email: str) -> str:
    """Mask email address for privacy in logs (e.g., j***n@gmail.com)"""
    if not email or '@' not in email:
        return '***'
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = local[0] + '***'
    else:
        masked_local = local[0] + '***' + local[-1]
    return f"{masked_local}@{domain}"


@dataclass
class Recipient:
    """Recipient configuration with search preferences"""
    email: str
    needs_sponsorship: bool
    search_terms: List[str]


def parse_recipients() -> List[Recipient]:
    """
    Parse recipient configuration from environment variables.

    Priority:
    1. RECIPIENTS (JSON array) - new format with per-recipient search terms
    2. RECIPIENT_EMAIL (string) - legacy fallback with global SEARCH_TERMS

    Returns:
        List of Recipient objects

    Raises:
        ValueError: If no valid recipient configuration found
    """
    # Try new JSON format first
    recipients_json = os.getenv("RECIPIENTS")

    if recipients_json:
        try:
            recipients_data = json.loads(recipients_json)
            recipients = []

            for r in recipients_data:
                email = r.get("email")
                if not email:
                    continue

                needs_sponsorship = r.get("needs_sponsorship", True)
                search_terms = r.get("search_terms", [])

                # Validate search_terms is a list
                if isinstance(search_terms, str):
                    search_terms = [term.strip() for term in search_terms.split(",") if term.strip()]
                elif not isinstance(search_terms, list):
                    search_terms = []

                # Normalize terms (merge groups) and deduplicate
                search_terms = list(dict.fromkeys(normalize_search_term(t) for t in search_terms))

                recipients.append(Recipient(
                    email=email,
                    needs_sponsorship=needs_sponsorship,
                    search_terms=search_terms
                ))

            # Debug: log recipients list (with masked emails)
            logger.debug(f"{len(recipients)} recipient(s) loaded")
            for i, r in enumerate(recipients):
                logger.debug(f"recipient[{i}] = email={mask_email(r.email)}, needs_sponsorship={r.needs_sponsorship}, search_terms={r.search_terms}")

            if recipients:
                logger.info(f"Loaded {len(recipients)} recipient(s) from RECIPIENTS config")
                return recipients

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid RECIPIENTS JSON: {e}")
            # Fall through to legacy format

    # Legacy fallback: single recipient with global search terms
    recipient_email = os.getenv("RECIPIENT_EMAIL")

    if not recipient_email:
        raise ValueError(
            "No recipient configuration found. "
            "Set RECIPIENTS (JSON) or RECIPIENT_EMAIL environment variable."
        )

    # Get global search terms for legacy mode
    search_terms_str = os.getenv("SEARCH_TERMS", "entry level software engineer")
    search_terms = [term.strip() for term in search_terms_str.split(",") if term.strip()]
    search_terms = list(dict.fromkeys(normalize_search_term(t) for t in search_terms))

    logger.info(f"Using legacy config: {mask_email(recipient_email)} (needs_sponsorship=True)")

    return [Recipient(
        email=recipient_email,
        needs_sponsorship=True,  # Legacy default
        search_terms=search_terms
    )]


def get_all_search_terms(recipients: List[Recipient]) -> List[str]:
    """
    Collect all unique search terms across all recipients.

    Args:
        recipients: List of Recipient objects

    Returns:
        List of unique search terms (preserves first occurrence order)
    """
    seen = set()
    unique_terms = []

    for recipient in recipients:
        for term in recipient.search_terms:
            term_normalized = normalize_search_term(term)
            term_lower = term_normalized.lower()
            if term_lower and term_lower not in seen:
                seen.add(term_lower)
                unique_terms.append(term_normalized)

    return unique_terms


def main():
    """Test configuration parsing"""
    logging.basicConfig(level=logging.DEBUG)
    logger.info("Testing configuration parsing...")

    # Test normalization helpers
    logger.info("\n--- Normalization Tests ---")
    logger.info(f"normalize('business analyst') -> '{normalize_search_term('business analyst')}'")
    logger.info(f"normalize('data analyst') -> '{normalize_search_term('data analyst')}'")
    logger.info(f"normalize('product manager') -> '{normalize_search_term('product manager')}'")
    logger.info(f"get_results_wanted('product manager') -> {get_results_wanted('product manager')}")
    logger.info(f"get_results_wanted('data scientist') -> {get_results_wanted('data scientist')}")
    logger.info(f"get_results_wanted('data engineer') -> {get_results_wanted('data engineer')}")
    logger.info(f"get_results_wanted('business analyst/data analyst') -> {get_results_wanted('business analyst/data analyst')}")
    logger.info(f"get_results_wanted('software engineer') -> {get_results_wanted('software engineer')}")
    logger.info(f"get_scrape_queries('business analyst/data analyst') -> {get_scrape_queries('business analyst/data analyst')}")
    logger.info(f"get_scrape_queries('product manager') -> {get_scrape_queries('product manager')}")

    # Test with current env
    try:
        recipients = parse_recipients()
        logger.info(f"\nParsed {len(recipients)} recipient(s):")
        for r in recipients:
            logger.info(f"  - {mask_email(r.email)}")
            logger.info(f"    needs_sponsorship: {r.needs_sponsorship}")
            logger.info(f"    search_terms: {r.search_terms}")

        all_terms = get_all_search_terms(recipients)
        logger.info(f"All unique search terms: {all_terms}")

    except ValueError as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    main()
