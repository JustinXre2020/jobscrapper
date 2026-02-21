"""Prompt template for the Summarizer node."""

from typing import Dict, List

SUMMARIZER_SYSTEM = (
    "You are a job posting data extractor. Return valid JSON only. No explanation."
)


def build_summarizer_prompt(job: Dict, search_terms: List[str]) -> str:
    """Build the user prompt for the Summarizer node.

    Args:
        job: Raw job dict with title, company, location, description.
        search_terms: Target roles for context.

    Returns:
        Formatted user prompt string.
    """
    title = str(job.get("title", "Unknown"))
    company = str(job.get("company", "Unknown"))
    location = str(job.get("location", "Unknown"))
    description = str(job.get("description", ""))
    search_terms_str = ", ".join(search_terms)

    return f"""### RAW JOB POSTING
Job Title: {title}
Company: {company}
Location: {location}
Target Roles: [{search_terms_str}]

Description:
{description}

### EXAMPLE OUTPUT
{{
  "title_normalized": "Software Engineer",
  "role_type": "software_engineering",
  "seniority_level": "senior",
  "years_experience_required": 5,
  "education_required": "bachelors",
  "visa_statements": ["must be authorized to work in the US"],
  "is_internship_coop": false,
  "key_requirements": ["Python", "AWS", "3+ years backend"],
  "description_summary": "Backend role focused on cloud services."
}}

### FIELD RULES
1. title_normalized - Remove seniority words (Senior, Lead, Junior, Staff, Principal, I, II, III, IV). "Senior Data Analyst II" becomes "Data Analyst".
2. role_type - One of: software_engineering, data_science, data_engineering, data_analysis, product_management, project_management, design, devops, security, qa, other.
3. seniority_level - One of: intern, entry, mid, senior, lead, staff, principal, director, vp, unknown. Use title keywords and years required.
4. years_experience_required - Minimum years from requirements section. null if not stated.
5. education_required - One of: none, high_school, bachelors, masters, phd, unknown. Mandatory minimum only.
6. visa_statements - Copy sentences about work authorization or visa sponsorship. Empty list if none mentioned.
7. is_internship_coop - true if internship, co-op, fellowship, or apprenticeship.
8. key_requirements - Main mandatory requirements (up to 8). Fewer is fine.
9. description_summary - 1-3 sentence role summary.

Respond ONLY with valid JSON."""
