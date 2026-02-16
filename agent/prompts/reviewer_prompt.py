"""Prompt template for the Reviewer node (LLM-as-Judge)."""

from typing import Dict, List

REVIEWER_SYSTEM = (
    "You are a QA specialist for job evaluation accuracy. "
    "Your role is to verify that an Analyzer's evaluation is logically consistent "
    "with the structured job summary data. Flag contradictions and errors."
)


def build_reviewer_prompt(
    summary: Dict,
    evaluation: Dict,
    search_terms: List[str],
) -> str:
    """Build the user prompt for the Reviewer node.

    Args:
        summary: Structured JobSummaryModel data (dict).
        evaluation: Analyzer's JobEvaluation data (dict).
        search_terms: Target roles for context.

    Returns:
        Formatted user prompt string.
    """
    search_terms_str = ", ".join(search_terms)

    return f"""### TASK
You are reviewing an Analyzer's evaluation of a job posting for logical consistency.
Compare the evaluation against the structured job summary data and flag any contradictions.

### STRUCTURED JOB SUMMARY
Title (normalized): {summary.get('title_normalized', 'Unknown')}
Role Type: {summary.get('role_type', 'unknown')}
Seniority Level: {summary.get('seniority_level', 'unknown')}
Years Experience Required: {summary.get('years_experience_required', 'Not specified')}
Education Required: {summary.get('education_required', 'unknown')}
Is Internship/Co-op: {summary.get('is_internship_coop', False)}
Visa Statements: {summary.get('visa_statements', [])}
Key Requirements: {summary.get('key_requirements', [])}
Description Summary: {summary.get('description_summary', '')}

### ANALYZER'S EVALUATION
keyword_match: {evaluation.get('keyword_match')}
visa_sponsorship: {evaluation.get('visa_sponsorship')}
entry_level: {evaluation.get('entry_level')}
requires_phd: {evaluation.get('requires_phd')}
is_internship: {evaluation.get('is_internship')}
reason: {evaluation.get('reason', '')}

Target Roles: [{search_terms_str}]

### REVIEW CRITERIA
Check each field for logical consistency:

1. **keyword_match**: Does the normalized title match any target role? If seniority_level is ignored, does the role_type align with the target roles?

2. **visa_sponsorship**: If visa_statements is empty, this MUST be True (silence = True). If visa_statements contain explicit bars ("must be US citizen", "no sponsorship"), this should be False.

3. **entry_level**: Check for contradictions:
   - If years_experience_required >= 1 but entry_level=True -> CONTRADICTION
   - If seniority_level is "senior"/"lead"/"staff" but entry_level=True -> CONTRADICTION
   - If years_experience_required is null/0 and seniority_level is "entry"/"intern"/"unknown" and entry_level=False -> POSSIBLE ERROR

4. **requires_phd**: If education_required != "phd" but requires_phd=True -> CONTRADICTION

5. **is_internship**: If is_internship_coop from summary differs from is_internship in evaluation -> CONTRADICTION

### OUTPUT FORMAT
Respond with JSON:
{{
    "approved": true/false,
    "feedback": "If not approved: specific correction explaining what the Analyzer got wrong and the correct value based on the data. If approved: brief confirmation."
}}"""
