"""Test fixtures: 4 realistic job postings covering key edge cases.

Each fixture is a dict with:
  - job: Raw job dict (title, company, location, description)
  - search_terms: Target roles for context
  - expected_summary: Key fields the summarizer should extract
  - expected_evaluation: Expected analyzer output given correct summary
"""

from typing import Any, Dict, List, TypedDict


class ExpectedSummary(TypedDict, total=False):
    seniority_level: str
    years_experience_required: int | None
    is_internship_coop: bool
    role_type: str
    education_required: str
    visa_statements_nonempty: bool  # True if visa_statements should be non-empty


class ExpectedEvaluation(TypedDict, total=False):
    keyword_match: bool
    visa_sponsorship: bool
    job_level: str
    requires_phd: bool


class JobFixture(TypedDict):
    job: Dict[str, Any]
    search_terms: List[str]
    expected_summary: ExpectedSummary
    expected_evaluation: ExpectedEvaluation


# --- Fixture 1: Senior role, visa denial, non-entry ---

SENIOR_EMBEDDED_ENGINEER: JobFixture = {
    "job": {
        "title": "Sr. Embedded Software Engineer",
        "company": "Northrop Grumman",
        "location": "Baltimore, MD, US",
        "description": (
            "Sr. Embedded Software Engineer\n\n"
            "Northrop Grumman is seeking a Sr. Embedded Software Engineer to join "
            "our team in Baltimore, MD. This role involves developing real-time "
            "embedded systems for defense applications.\n\n"
            "Requirements:\n"
            "- 8+ years of experience in embedded C/C++ development\n"
            "- Bachelor's degree in Computer Science, Electrical Engineering, or related field\n"
            "- Experience with RTOS (VxWorks, INTEGRITY, or similar)\n"
            "- Strong understanding of hardware/software integration\n"
            "- Experience with DO-178C or similar safety-critical standards\n\n"
            "US Citizenship is required. This position requires an active Secret clearance "
            "or the ability to obtain one. No visa sponsorship available.\n\n"
            "Preferred: Master's degree, experience with FPGA integration, "
            "familiarity with JIRA and Git."
        ),
    },
    "search_terms": ["software engineer"],
    "expected_summary": {
        "seniority_level": "senior",
        "years_experience_required": 8,
        "is_internship_coop": False,
        "role_type": "software_engineering",
        "education_required": "bachelors",
        "visa_statements_nonempty": True,
    },
    "expected_evaluation": {
        "keyword_match": True,
        "visa_sponsorship": False,
        "job_level": "senior",
        "requires_phd": False,
    },
}

SAP_INTERN: JobFixture = {
    "job": {
        "title": "SAP Intern - Business Transformation",
        "company": "Deloitte",
        "location": "New York, NY, US",
        "description": (
            "SAP Intern - Business Transformation\n\n"
            "Join Deloitte's Consulting practice as an SAP Intern and gain hands-on "
            "experience supporting enterprise transformation projects.\n\n"
            "As an intern, you will assist senior consultants with SAP S/4HANA "
            "implementation projects, help gather and document business requirements, "
            "and participate in testing and data migration activities.\n\n"
            "Qualifications:\n"
            "- Currently pursuing a Bachelor's or Master's degree in Information Systems, "
            "Business, Computer Science, or related field\n"
            "- Expected graduation between December 2026 and June 2027\n"
            "- Interest in enterprise technology and business process improvement\n"
            "- Strong analytical and communication skills\n\n"
            "This is a paid summer internship (10-12 weeks). Must be legally authorized "
            "to work in the United States without the need for employer sponsorship, "
            "now or at any time in the future."
        ),
    },
    "search_terms": ["business analyst", "data analyst"],
    "expected_summary": {
        "seniority_level": "intern",
        "years_experience_required": None,
        "is_internship_coop": True,
        "role_type": "other",
        "visa_statements_nonempty": True,
    },
    "expected_evaluation": {
        "keyword_match": False,
        "visa_sponsorship": False,
        "job_level": "internship",
        "requires_phd": False,
    },
}


# --- Fixture 3: Mid-level, export control visa nuance ---

RESEARCH_DEVOPS_ENGINEER: JobFixture = {
    "job": {
        "title": "Research DevOps Engineer",
        "company": "Applied Materials",
        "location": "Santa Clara, CA, US",
        "description": (
            "Research DevOps Engineer\n\n"
            "Applied Materials is looking for a Research DevOps Engineer to support "
            "our R&D infrastructure. You will build and maintain CI/CD pipelines, "
            "automate testing workflows, and manage cloud-based development environments.\n\n"
            "Requirements:\n"
            "- 3+ years of experience with CI/CD tools (Jenkins, GitLab CI, or GitHub Actions)\n"
            "- Proficiency in Python and Bash scripting\n"
            "- Experience with Docker and Kubernetes\n"
            "- Bachelor's degree in Computer Science or related field\n"
            "- Familiarity with AWS or Azure cloud services\n\n"
            "This position is subject to Export Administration Regulations (EAR). "
            "Candidates must be a U.S. Person (U.S. citizen, permanent resident, "
            "or protected individual under 8 U.S.C. 1324b(a)(3)).\n\n"
            "Nice to have: Terraform, Ansible, monitoring with Prometheus/Grafana."
        ),
    },
    "search_terms": ["software engineer", "devops engineer"],
    "expected_summary": {
        "seniority_level": "mid",
        "years_experience_required": 3,
        "is_internship_coop": False,
        "role_type": "devops",
        "education_required": "bachelors",
        "visa_statements_nonempty": True,
    },
    "expected_evaluation": {
        "keyword_match": True,
        "visa_sponsorship": False,
        "job_level": "mid",
        "requires_phd": False,
    },
}


# --- Fixture 4: Junior/entry-level, no special reqs, short description ---

JUNIOR_SOFTWARE_ENGINEER: JobFixture = {
    "job": {
        "title": "Junior Software Engineer",
        "company": "TechStartup Inc.",
        "location": "Austin, TX, US",
        "description": (
            "Junior Software Engineer\n\n"
            "We are a growing startup looking for a Junior Software Engineer to join "
            "our engineering team. You will work on our web platform using React and "
            "Node.js, collaborate with designers and product managers, and ship "
            "features to production weekly.\n\n"
            "What we're looking for:\n"
            "- Bachelor's degree in CS or equivalent practical experience\n"
            "- Familiarity with JavaScript/TypeScript\n"
            "- Basic understanding of REST APIs and databases\n"
            "- Eagerness to learn and grow\n\n"
            "This is a great opportunity for recent graduates or those early in their "
            "career. We offer mentorship, flexible work hours, and competitive benefits."
        ),
    },
    "search_terms": ["software engineer"],
    "expected_summary": {
        "seniority_level": "entry",
        "years_experience_required": None,
        "is_internship_coop": False,
        "role_type": "software_engineering",
        "visa_statements_nonempty": False,
    },
    "expected_evaluation": {
        "keyword_match": True,
        "visa_sponsorship": True,
        "job_level": "entry",
        "requires_phd": False,
    },
}


ALL_FIXTURES: List[JobFixture] = [
    SENIOR_EMBEDDED_ENGINEER,
    SAP_INTERN,
    RESEARCH_DEVOPS_ENGINEER,
    JUNIOR_SOFTWARE_ENGINEER,
]

FIXTURE_IDS: List[str] = [
    "senior_embedded",
    "sap_intern",
    "research_devops",
    "junior_swe",
]
