"""Evaluation dataset with ground-truth labels for measuring agent accuracy.

Each fixture provides a pre-built summary (bypassing summarizer) and the expected
evaluation output. Covers edge cases identified from reviewer feedback analysis.
"""

from typing import Any, Dict, List, Optional, TypedDict


class EvalExpected(TypedDict, total=False):
    keyword_match: bool
    visa_sponsorship: bool
    entry_level: bool
    is_internship: bool
    requires_phd: bool


class EvalFixture(TypedDict):
    id: str
    summary: Dict[str, Any]
    search_terms: List[str]
    expected: EvalExpected


# --- Entry-level edge cases ---

ENTRY_0_YEARS: EvalFixture = {
    "id": "entry_0yr_entry_seniority",
    "summary": {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "entry",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["JavaScript", "React", "REST APIs"],
        "description_summary": "Entry-level web developer at a startup.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": True,
        "is_internship": False,
        "requires_phd": False,
    },
}

ENTRY_1_YEAR: EvalFixture = {
    "id": "entry_1yr_entry_seniority",
    "summary": {
        "title_normalized": "Business Analyst",
        "role_type": "business_analysis",
        "seniority_level": "entry",
        "years_experience_required": 1,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["SQL", "Excel", "data analysis"],
        "description_summary": "Entry-level analyst role requiring 1 year experience.",
    },
    "search_terms": ["business analyst", "data analyst"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": True,
        "is_internship": False,
        "requires_phd": False,
    },
}

MID_3_YEARS: EvalFixture = {
    "id": "mid_3yr",
    "summary": {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "mid",
        "years_experience_required": 3,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["Python", "Django", "PostgreSQL", "AWS"],
        "description_summary": "Mid-level backend engineer, 3+ years required.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

SENIOR_NULL_YEARS: EvalFixture = {
    "id": "senior_null_years",
    "summary": {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "senior",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["System design", "mentoring", "Java"],
        "description_summary": "Senior engineer role, no explicit years stated.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

PRINCIPAL_NULL_YEARS: EvalFixture = {
    "id": "principal_null_years",
    "summary": {
        "title_normalized": "Product Manager",
        "role_type": "product_management",
        "seniority_level": "principal",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["Product strategy", "stakeholder management"],
        "description_summary": "Principal PM at a large tech company.",
    },
    "search_terms": ["product manager"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

# --- Visa sponsorship edge cases ---

VISA_EMPTY: EvalFixture = {
    "id": "visa_empty_statements",
    "summary": {
        "title_normalized": "Data Analyst",
        "role_type": "data_analysis",
        "seniority_level": "entry",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["SQL", "Python", "Tableau"],
        "description_summary": "Data analyst role with no visa info mentioned.",
    },
    "search_terms": ["data analyst"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": True,
        "is_internship": False,
        "requires_phd": False,
    },
}

VISA_EXPLICIT_DENIAL: EvalFixture = {
    "id": "visa_explicit_denial",
    "summary": {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "mid",
        "years_experience_required": 3,
        "education_required": "bachelors",
        "visa_statements": ["No visa sponsorship available"],
        "is_internship_coop": False,
        "key_requirements": ["C++", "Linux", "networking"],
        "description_summary": "Mid-level SWE, no visa sponsorship.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": False,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

VISA_US_PERSON: EvalFixture = {
    "id": "visa_us_person_required",
    "summary": {
        "title_normalized": "DevOps Engineer",
        "role_type": "devops",
        "seniority_level": "mid",
        "years_experience_required": 3,
        "education_required": "bachelors",
        "visa_statements": ["Candidates must be a U.S. Person"],
        "is_internship_coop": False,
        "key_requirements": ["CI/CD", "Docker", "Kubernetes"],
        "description_summary": "DevOps role with US Person requirement.",
    },
    "search_terms": ["devops engineer", "software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": False,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

VISA_SPONSORSHIP_AVAILABLE: EvalFixture = {
    "id": "visa_sponsorship_available",
    "summary": {
        "title_normalized": "Machine Learning Engineer",
        "role_type": "machine_learning",
        "seniority_level": "mid",
        "years_experience_required": 2,
        "education_required": "masters",
        "visa_statements": ["Visa sponsorship is available for this position"],
        "is_internship_coop": False,
        "key_requirements": ["PyTorch", "TensorFlow", "NLP"],
        "description_summary": "ML engineer with visa sponsorship available.",
    },
    "search_terms": ["machine learning engineer", "software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

# --- Internship cases ---

INTERNSHIP_TITLE: EvalFixture = {
    "id": "internship_title_keyword",
    "summary": {
        "title_normalized": "Software Engineering Intern",
        "role_type": "software_engineering",
        "seniority_level": "intern",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": True,
        "key_requirements": ["Python", "data structures"],
        "description_summary": "Summer SWE internship for undergrads.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": True,
        "is_internship": True,
        "requires_phd": False,
    },
}

NOT_INTERNSHIP: EvalFixture = {
    "id": "not_internship_fulltime",
    "summary": {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "entry",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["Go", "microservices"],
        "description_summary": "Full-time entry-level SWE position.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": True,
        "is_internship": False,
        "requires_phd": False,
    },
}

# --- PhD cases ---

PHD_REQUIRED: EvalFixture = {
    "id": "phd_required",
    "summary": {
        "title_normalized": "Research Scientist",
        "role_type": "research",
        "seniority_level": "mid",
        "years_experience_required": 2,
        "education_required": "phd",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["PhD in CS or related", "publications", "deep learning"],
        "description_summary": "Research scientist requiring PhD.",
    },
    "search_terms": ["research scientist", "software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": True,
    },
}

PHD_NOT_REQUIRED: EvalFixture = {
    "id": "phd_not_required_masters",
    "summary": {
        "title_normalized": "Data Scientist",
        "role_type": "data_science",
        "seniority_level": "mid",
        "years_experience_required": 2,
        "education_required": "masters",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["Python", "statistics", "ML"],
        "description_summary": "Data scientist, masters preferred.",
    },
    "search_terms": ["data scientist"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

# --- Keyword match/mismatch ---

KEYWORD_MISMATCH: EvalFixture = {
    "id": "keyword_mismatch",
    "summary": {
        "title_normalized": "Product Manager",
        "role_type": "product_management",
        "seniority_level": "mid",
        "years_experience_required": 5,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["Product roadmap", "Agile", "stakeholder mgmt"],
        "description_summary": "PM role at a SaaS company.",
    },
    "search_terms": ["software engineer", "data analyst"],
    "expected": {
        "keyword_match": False,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

KEYWORD_MATCH_DIFFERENT_SENIORITY: EvalFixture = {
    "id": "keyword_match_ignore_seniority",
    "summary": {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "staff",
        "years_experience_required": 10,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["Architecture", "system design", "leadership"],
        "description_summary": "Staff-level SWE, 10+ years.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

# --- Combined edge cases ---

ENTRY_WITH_VISA_DENIAL: EvalFixture = {
    "id": "entry_with_visa_denial",
    "summary": {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "entry",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [
            "Must be legally authorized to work without sponsorship"
        ],
        "is_internship_coop": False,
        "key_requirements": ["Python", "SQL"],
        "description_summary": "Entry SWE, no visa sponsorship.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": False,
        "entry_level": True,
        "is_internship": False,
        "requires_phd": False,
    },
}

COOP_TITLE: EvalFixture = {
    "id": "coop_in_title",
    "summary": {
        "title_normalized": "Data Analyst Co-op",
        "role_type": "data_analysis",
        "seniority_level": "intern",
        "years_experience_required": None,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": True,
        "key_requirements": ["Excel", "SQL"],
        "description_summary": "Co-op data analyst position for students.",
    },
    "search_terms": ["data analyst"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": True,
        "is_internship": True,
        "requires_phd": False,
    },
}

LEAD_WITH_2_YEARS: EvalFixture = {
    "id": "lead_2yr",
    "summary": {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "lead",
        "years_experience_required": 2,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["Team leadership", "Java", "Spring Boot"],
        "description_summary": "Lead engineer role, 2+ years.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

DIRECTOR_ROLE: EvalFixture = {
    "id": "director_role",
    "summary": {
        "title_normalized": "Engineering Manager",
        "role_type": "engineering_management",
        "seniority_level": "director",
        "years_experience_required": 10,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["People management", "budgeting", "strategy"],
        "description_summary": "Director of engineering at a Fortune 500.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": False,
        "visa_sponsorship": True,
        "entry_level": False,
        "is_internship": False,
        "requires_phd": False,
    },
}

UNKNOWN_SENIORITY_1_YEAR: EvalFixture = {
    "id": "unknown_seniority_1yr",
    "summary": {
        "title_normalized": "Software Engineer",
        "role_type": "software_engineering",
        "seniority_level": "unknown",
        "years_experience_required": 1,
        "education_required": "bachelors",
        "visa_statements": [],
        "is_internship_coop": False,
        "key_requirements": ["JavaScript", "Node.js"],
        "description_summary": "SWE role with 1 year req, seniority unclear.",
    },
    "search_terms": ["software engineer"],
    "expected": {
        "keyword_match": True,
        "visa_sponsorship": True,
        # Ambiguous: unknown seniority + 1yr -> LLM decides, but lean True
        "entry_level": True,
        "is_internship": False,
        "requires_phd": False,
    },
}

# --- Aggregated list ---

EVAL_FIXTURES: List[EvalFixture] = [
    ENTRY_0_YEARS,
    ENTRY_1_YEAR,
    MID_3_YEARS,
    SENIOR_NULL_YEARS,
    PRINCIPAL_NULL_YEARS,
    VISA_EMPTY,
    VISA_EXPLICIT_DENIAL,
    VISA_US_PERSON,
    VISA_SPONSORSHIP_AVAILABLE,
    INTERNSHIP_TITLE,
    NOT_INTERNSHIP,
    PHD_REQUIRED,
    PHD_NOT_REQUIRED,
    KEYWORD_MISMATCH,
    KEYWORD_MATCH_DIFFERENT_SENIORITY,
    ENTRY_WITH_VISA_DENIAL,
    COOP_TITLE,
    LEAD_WITH_2_YEARS,
    DIRECTOR_ROLE,
    UNKNOWN_SENIORITY_1_YEAR,
]

EVAL_IDS: List[str] = [f["id"] for f in EVAL_FIXTURES]
