"""Shared Pydantic schemas used across agent nodes."""

from typing import List, Optional
from pydantic import BaseModel, Field


class JobSummaryModel(BaseModel):
    """Structured output from the Summarizer node."""

    title_normalized: str = Field(
        description="Standardized job title without seniority modifiers (e.g., 'Software Engineer' instead of 'Senior Software Engineer')"
    )
    role_type: str = Field(
        description="Professional function category (e.g., 'software_engineering', 'data_science', 'product_management')"
    )
    seniority_level: str = Field(
        description="Seniority tier: 'intern', 'entry', 'mid', 'senior', 'lead', 'staff', 'principal', 'director', 'vp', 'unknown'"
    )
    years_experience_required: Optional[int] = Field(
        default=None,
        description="Minimum years of experience required. None if not mentioned."
    )
    education_required: str = Field(
        description="Minimum education level: 'none', 'high_school', 'bachelors', 'masters', 'phd', 'unknown'"
    )
    visa_statements: List[str] = Field(
        default_factory=list,
        description="Exact phrases from the posting about work authorization, visa sponsorship, or citizenship requirements"
    )
    is_internship_coop: bool = Field(
        description="True if the role is an internship, co-op, fellowship, or apprenticeship"
    )
    key_requirements: List[str] = Field(
        default_factory=list,
        description="Main mandatory requirements from the posting (up to 8)"
    )
    description_summary: str = Field(
        description="2-3 sentence summary of what the role entails"
    )


class JobEvaluation(BaseModel):
    """Structured LLM output for job evaluation (migrated from llm_filter.py)."""

    keyword_match: bool = Field(
        description=(
            "True if the normalized job title represents the same professional function "
            "as any target role, regardless of seniority level."
        )
    )
    visa_sponsorship: bool = Field(
        description=(
            "Default True when visa_statements is empty. "
            "False only if there is an explicit denial such as "
            "'no visa sponsorship', 'must be US citizen', or 'authorized without sponsorship'."
        )
    )
    entry_level: bool = Field(
        description=(
            "True if years_experience_required is 0, 1, or null AND seniority_level is "
            "'entry' or 'intern'. False if years >= 2 or seniority is mid/senior/lead/staff "
            "or higher."
        )
    )
    requires_phd: bool = Field(
        description="True only if education_required is 'phd' as a mandatory requirement."
    )
    is_internship: bool = Field(
        description=(
            "True if is_internship_coop is true in the summary or the title contains "
            "'Intern', 'Internship', 'Co-op', 'Fellowship', or 'Apprenticeship'."
        )
    )
    reason: str = Field(
        description="Concise breakdown citing structured summary fields for each boolean."
    )


class ReviewResult(BaseModel):
    """Reviewer node output with confidence score and gap list."""

    approved: bool = Field(
        description="True if confidence >= threshold (default 70)"
    )
    confidence: int = Field(
        default=50,
        description="Confidence score 0-100 indicating how correct the Analyzer's evaluation is"
    )
    gap_list: List[str] = Field(
        default_factory=list,
        description="List of specific issues found in the evaluation (empty if approved)"
    )
    feedback: str = Field(
        description="Summary of issues found, or brief confirmation if approved."
    )


class BatchReviewSample(BaseModel):
    """A single sampled job in a batch review."""

    job_index: int = Field(description="Index of this job in the batch results list.")
    job_title: str = Field(default="")
    company: str = Field(default="")
    summary: Optional[dict] = Field(default=None)
    evaluation: Optional[dict] = Field(default=None)
    reviewer_agrees: bool = Field(
        default=True, description="Whether the reviewer agrees with the evaluation."
    )
    feedback: str = Field(default="", description="Reviewer feedback for this sample.")


class BatchReviewResult(BaseModel):
    """Result of reviewing a sample from the batch."""

    samples_reviewed: int = Field(default=0)
    disagreements: int = Field(default=0)
    approved: bool = Field(
        default=True,
        description="True if disagreements < threshold (default 2).",
    )
    sample_details: List[BatchReviewSample] = Field(default_factory=list)


class HumanReviewDecision(BaseModel):
    """A single human review decision for a flagged job."""

    job_title: str = Field(default="")
    company: str = Field(default="")
    agrees_with_evaluation: bool = Field(
        default=True,
        description="Whether the human agrees with the LLM evaluation.",
    )
    corrected_evaluation: Optional[dict] = Field(
        default=None,
        description="Human-corrected evaluation fields, if any.",
    )
    feedback: str = Field(
        default="", description="Human-provided feedback for this job."
    )
