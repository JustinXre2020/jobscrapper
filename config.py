"""
Recipient configuration for Job Hunter Sentinel
Supports multi-recipient with per-recipient search terms and sponsorship needs
"""
import os
import json
import logging
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


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
            term_lower = term.lower().strip()
            if term_lower and term_lower not in seen:
                seen.add(term_lower)
                unique_terms.append(term.strip())

    return unique_terms


def main():
    """Test configuration parsing"""
    logging.basicConfig(level=logging.DEBUG)
    logger.info("Testing configuration parsing...")

    # Test with current env
    try:
        recipients = parse_recipients()
        logger.info(f"Parsed {len(recipients)} recipient(s):")
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
