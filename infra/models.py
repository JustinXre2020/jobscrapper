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
        description="True if the job title matches any target role (ignoring seniority modifiers like Senior, Lead, Staff, etc.)"
    )
    visa_sponsorship: bool = Field(
        description="True unless the posting explicitly bars visa holders. Default True if silent on sponsorship."
    )
    entry_level: bool = Field(
        description="True only if 0 years experience required, title contains Junior/Associate/Entry-Level with no years mentioned, or explicitly states no experience required."
    )
    requires_phd: bool = Field(
        description="True only if a PhD/doctorate is listed as a mandatory requirement, not merely preferred."
    )
    is_internship: bool = Field(
        description="True if the role is an internship, co-op, fellowship, or apprenticeship."
    )
    reason: str = Field(
        description="Concise breakdown of the logic used for each field, citing specific text from the posting."
    )


class ReviewResult(BaseModel):
    """Reviewer node output."""

    approved: bool = Field(
        description="True if the Analyzer's evaluation is logically consistent with the structured summary data"
    )
    feedback: str = Field(
        description="If not approved: specific correction text explaining what the Analyzer got wrong and why. If approved: brief confirmation."
    )
