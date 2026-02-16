"""Prompt template for the Analyzer node.

Migrated from llm_filter.py _create_prompt(), adapted to operate on
structured JobSummary data instead of raw description text.
"""

from typing import Dict, List, Optional

ANALYZER_SYSTEM = (
    "You are an expert Recruitment Consultant and Talent Acquisition Specialist "
    "across all industries. You specialize in mapping job titles to standardized "
    "job families, understanding that different companies use different nomenclature "
    "for the same professional role."
)


def build_analyzer_prompt(
    summary: Dict,
    search_terms: List[str],
    accumulated_feedback: Optional[List[str]] = None,
    review_feedback: Optional[str] = None,
) -> str:
    """Build the user prompt for the Analyzer node.

    Args:
        summary: Structured JobSummaryModel data (dict).
        search_terms: Target roles to match against.
        accumulated_feedback: Historic reviewer corrections to improve accuracy.
        review_feedback: Specific feedback from the Reviewer on a retry.

    Returns:
        Formatted user prompt string.
    """
    search_terms_str = ", ".join(search_terms)

    # Build feedback section if any corrections exist
    feedback_section = ""
    if review_feedback:
        feedback_section += f"""
### REVIEWER CORRECTION (address this in your analysis)
{review_feedback}
"""
    if accumulated_feedback:
        corrections = "\n".join(f"- {fb}" for fb in accumulated_feedback[-20:])
        feedback_section += f"""
### PAST CORRECTIONS (avoid these mistakes)
{corrections}
"""

    return f"""### STRUCTURED JOB DATA
Title (normalized): {summary.get('title_normalized', 'Unknown')}
Role Type: {summary.get('role_type', 'unknown')}
Seniority Level: {summary.get('seniority_level', 'unknown')}
Years Experience Required: {summary.get('years_experience_required', 'Not specified')}
Education Required: {summary.get('education_required', 'unknown')}
Is Internship/Co-op: {summary.get('is_internship_coop', False)}
Visa Statements: {summary.get('visa_statements', [])}
Key Requirements: {summary.get('key_requirements', [])}
Description Summary: {summary.get('description_summary', '')}

Target Roles: [{search_terms_str}]
{feedback_section}
### INSTRUCTIONS
Using the structured data above, evaluate the job on these criteria:

1. **keyword_match**: (true/false)
   - Compare the normalized job title against the Target Roles list.
   - Return TRUE if the title represents the same professional function as any target role, regardless of seniority.
   - Seniority modifiers to ignore: Senior, Lead, Staff, Principal, Junior, Entry-level, I, II, III, IV, etc.
   - Examples:
     * Title: "Software Engineer", Target: ["software engineer"] -> TRUE
     * Title: "Product Manager", Target: ["software engineer", "product manager"] -> TRUE
     * Title: "Data Scientist", Target: ["software engineer"] -> FALSE

2. **visa_sponsorship**: (true/false)
   - Check the visa_statements field.
   - DEFAULT to TRUE if visa_statements is empty (silence = TRUE).
   - Return FALSE ONLY if there is an explicit negative statement like:
     * "Must be a US Citizen or Permanent Resident"
     * "No visa sponsorship available"
     * "Candidates must be authorized to work without sponsorship"
   - Return TRUE if sponsorship is mentioned as available or no mention at all.

3. **is_internship**: (true/false)
   - Use the is_internship_coop field directly.
   - Also return TRUE if the title contains "Intern", "Internship", "Co-op", "Fellowship", or "Apprenticeship".

4. **entry_level**: (true/false)
   - Use seniority_level and years_experience_required from the structured data.
   - Return TRUE ONLY if ONE of these conditions is met:
     a) years_experience_required is 0 or null AND seniority_level is "entry" or "intern"
     b) years_experience_required starts with 0 (e.g., "0-2 years")
     c) The description explicitly states "No experience required"
   - Return FALSE if years_experience_required >= 1.
   - Return FALSE if seniority_level is "mid", "senior", "lead", "staff", "principal", "director", or "vp".

5. **requires_phd**: (true/false)
   - Check education_required field.
   - Return TRUE only if education_required is "phd" (mandatory, not preferred).

### OUTPUT FORMAT
Respond ONLY with valid JSON:
{{
    "keyword_match": boolean,
    "visa_sponsorship": boolean,
    "entry_level": boolean,
    "requires_phd": boolean,
    "is_internship": boolean,
    "reason": "Concise breakdown citing structured data for each field."
}}"""
