# Copilot Instructions for Job Hunter Sentinel

This file provides guidance for GitHub Copilot when working with this codebase.

## Project Overview

Job Hunter Sentinel — an automated job scraping and recommendation system for O-1 visa applicants. Scrapes jobs from multiple boards, filters them with an LLM-based agent pipeline using LangGraph + Reflexion architecture, and emails matched jobs to recipients. Runs on GitHub Actions twice daily (6 AM & 1 PM EST).

## Build, Test, and Lint Commands

### Setup
```bash
# One-click setup (installs uv, creates venv, installs deps)
./setup.sh

# Manual setup
uv venv .venv && source .venv/bin/activate && uv pip install -e .
```

### Running the Application
```bash
# Run the full pipeline
python main.py

# Test individual modules
python scraper.py        # Job scraping only
python ai_analyzer.py    # Legacy AI analysis
```

### Testing
```bash
# All tests
pytest tests/

# Single test file with verbose output
pytest tests/test_summarizer.py -v

# Only tests hitting real APIs (requires OPENROUTER_API_KEY)
pytest -m live

# Run with specific model
TEST_MODELS="liquid/lfm-2.5-1.2b-instruct:free" pytest tests/
```

### Linting & Formatting
```bash
# Lint (rules: E, F, I, N, W; ignores E501)
ruff check .

# Format check
black --check .

# Auto-format
black .
```

## High-Level Architecture

### Pipeline Flow
Orchestrated in `main.py`:
1. **Scrape** (`scraper.py`) — python-jobspy across LinkedIn, Indeed, ZipRecruiter, Google Jobs
2. **Deduplicate** (`storage/database.py`) — SQLite via SQLAlchemy, fallback to text file
3. **LLM Filter** — LangGraph agent (`filtering/job_filter.py` + `agent/`) or legacy modes
4. **Email** (`notification/email_sender.py`) — Gmail SMTP with per-recipient filtering
5. **Cleanup** (`storage/data_manager.py`) — JSON/CSV storage, auto-deletes files >7 days

### Two-Level LangGraph Architecture (Reflexion)

**Inner graph** (per-job, `agent/graph.py`):
```
[Summarizer] → [Analyzer] → [Reviewer] ──→ END (confidence ≥ 70)
                    ↑             │
                    │    (confidence < 70 AND retry < max)
                    └─────────────┘ (with Gap List feedback)
                              │
                    (confidence < 70 AND retry >= max)
                              ↓
                    [needs_human_review = True] → END
```

- **Summarizer** (`agent/nodes/summarizer.py`): Extracts structured job metadata via LLM
- **Analyzer** (`agent/nodes/analyzer.py`): LLM + deterministic eval + forced Chain-of-Thought + Reflexion feedback
- **Reviewer** (`agent/nodes/reviewer.py`): Rubric-based strict critic producing confidence score (0-100) + gap list
- Deterministic overrides for unambiguous fields (visa, internship, PhD, clear seniority)
- On retry: Analyzer receives structured gap list feedback for self-correction
- Exhausted retries: job flagged `needs_human_review=True`

**Outer graph** (per-batch, `agent/batch_graph.py`):
```
[Process All Jobs] → [Batch Reviewer] → [Collect Uncertain] → [Human Review] → [Save Decisions] → END
       ↑                                                              |
       +---- (2+ disagreements, redo < max) --------------------------+
```

- **Batch Reviewer**: Samples 10 jobs from batch, threshold 2 disagreements triggers full batch redo
- **Collect Uncertain**: Gathers jobs where `needs_human_review=True` from inner graph
- **Human Review**: LangGraph `interrupt()` for CLI human-in-the-loop (presents both batch disagreements and uncertain jobs)
- **Save Decisions**: Persists to `data/human_review_results.json` (by search term) and feedback store
- CI mode (`ENABLE_HUMAN_REVIEW=false`): uncertain jobs auto-accepted with warning log

**Legacy workflow** (`USE_LEGACY_WORKFLOW=true`):
```
[Summarizer] → [Analyzer] → [Reviewer] → END
                   ↑              ↓ (if rejected)
                   └──────────────┘ (max 1 retry)
```

### Feedback Stores
- **JSONL** (default): Chronological, last 20 entries (`agent/feedback/store.py`)
- **Milvus vector** (`USE_VECTOR_FEEDBACK=true`): Semantic search via sentence-transformers embeddings (`agent/feedback/vector_store.py`)
- **Human review results** (`data/human_review_results.json`): Categorized by search term, loaded as high-confidence reference examples (`agent/feedback/human_review_store.py`)

### Multi-Recipient Architecture
Defined in `config.py`:
- `Recipient` dataclass: email, `needs_sponsorship` flag, per-recipient `search_terms`
- `SEARCH_TERM_GROUPS`: slash-separated terms expand to multiple queries
- `RESULTS_WANTED_MAP`: per-term scrape count overrides
- Legacy fallback: `RECIPIENT_EMAIL` + global `SEARCH_TERMS`

### LLM Client
`infra/llm_client.py`:
- AsyncOpenAI via OpenRouter with `instructor` for structured Pydantic output
- Per-call temperature override for parallel analyzer diversity
- Retries on 502/503/504 (2x, 5s base delay)
- Falls back to text mode + JSON repair (`infra/json_repair.py`) when structured output fails

## Key Conventions

### File Organization
```
main.py                 — Entry point; orchestrates pipeline
config.py               — Multi-recipient config, env var loading
scraper.py              — Job scraping via python-jobspy

filtering/              — Job filtering strategies
├── job_filter.py       — LangGraph agent-based filtering (current)
├── llm_filter.py       — OpenRouter single-call filter (legacy)
├── llm_filter_legacy.py — Rule-based + LLM filtering (legacy)
└── ai_analyzer.py      — Gemini AI analysis (legacy)

agent/                  — LangGraph workflow (Reflexion architecture)
├── graph.py            — Inner per-job graph
├── batch_graph.py      — Outer batch graph
├── state.py            — JobState + BatchState TypedDict definitions
├── nodes/              — Node implementations
├── prompts/            — System prompts for each node
└── feedback/           — Feedback store implementations

infra/                  — Shared infrastructure
├── llm_client.py       — AsyncOpenAI + instructor wrapper
├── models.py           — Pydantic schemas
├── embedding_client.py — sentence-transformers wrapper
└── json_repair.py      — JSON repair for malformed LLM output

storage/                — Data persistence
├── database.py         — SQLAlchemy dedup tracking, text-file fallback
└── data_manager.py     — JSON/CSV storage, auto-cleanup >7 days

notification/
└── email_sender.py     — Gmail SMTP dispatcher

tests/
├── conftest.py         — Pytest config, fixtures, model parametrization
├── test_*.py           — Agent node tests
└── fixtures/           — Test job data
```

### Async Throughout
- All LLM interactions use `asyncio` and `AsyncOpenAI`
- Parallel job processing controlled by `AGENT_CONCURRENCY` (default 5)
- Rate limiting with exponential backoff for 429s (2s → 4s → 8s)

### Structured Output
- Use Pydantic models + `instructor` for LLM output
- JSON repair as fallback for malformed responses
- Models defined in `infra/models.py`: `JobSummary`, `JobEvaluation`, `ReviewResult`, `BatchReviewResult`, etc.

### Deterministic Overrides
In `agent/nodes/analyzer.py`, certain fields have deterministic logic that overrides LLM output:
- `requires_sponsorship`: "US work authorization required" → True
- `internship`: Job title contains "intern" → True
- `requires_phd`: Job description mentions PhD requirement → True
- `seniority_level`: Clear indicators (e.g., "Senior", "Principal", "Staff") → override LLM

### Testing with Markers
- Use `@pytest.mark.live` for tests hitting real APIs
- These tests require `OPENROUTER_API_KEY` in environment
- Default test model: `liquid/lfm-2.5-1.2b-instruct:free`
- Override via `TEST_MODELS` environment variable

## Critical Environment Variables

See `.env.example` for full list. Key ones:

**Email Configuration:**
- `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` — sender credentials (App Password, not account password)
- `RECIPIENTS` — JSON array of `{email, needs_sponsorship, search_terms}` objects

**LLM Configuration:**
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — LLM access

**Workflow Mode:**
- `USE_AGENT_WORKFLOW` — `true` for LangGraph agent, `false` for legacy filter
- `USE_LEGACY_WORKFLOW` — `true` for legacy per-job workflow, `false` for Reflexion batch workflow

**Agent Tuning:**
- `REVIEWER_CONFIDENCE_THRESHOLD` — confidence cutoff for Reviewer pass/fail (default 70)
- `MAX_ANALYZER_RETRIES` — max Analyzer retries per job when confidence below threshold (default 1)
- `ENABLE_HUMAN_REVIEW` — `true` for CLI human-in-the-loop (disable for CI)
- `USE_VECTOR_FEEDBACK` — `true` for Milvus vector feedback store
- `AGENT_CONCURRENCY` — parallel job processing limit (default 5)

**Scraping:**
- `SEARCH_TERMS`, `LOCATIONS`, `HOURS_OLD`, `SITES`, `RESULTS_WANTED` — scraping parameters
- `DATABASE_URL` — SQLite path or PostgreSQL/Supabase URI

## Code Style

- Python 3.10+, line length 100
- Ruff rules: E, F, I, N, W (E501 ignored for long lines)
- Black: line-length=100, target py310/py311
- All async code uses `asyncio`
- Structured logging throughout (consider using `logger.info`, `logger.warning`, etc.)

## Common Tasks

### Adding a New Agent Node
1. Create node file in `agent/nodes/`
2. Define async function taking `state: JobState` or `state: BatchState`
3. Add system prompt in `agent/prompts/`
4. Update graph in `agent/graph.py` or `agent/batch_graph.py`
5. Add tests in `tests/test_[nodename].py` with `@pytest.mark.live`

### Modifying Filtering Logic
- Current: `filtering/job_filter.py` + `agent/` modules
- Legacy modes available for fallback/comparison

### Changing Email Templates
Edit `notification/email_sender.py`:
- `create_email_body()` — overall email structure
- `create_job_html()` — individual job cards

### Updating Scraping Sources
Modify `scraper.py`:
- `self.sites` list (must be supported by python-jobspy)
- Adjust `SITES` environment variable

### Database Fallback
If SQLite/Supabase fails, system auto-downgrades to `sent_jobs.txt` text file for deduplication.
