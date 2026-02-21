# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Job Hunter Sentinel — an automated job scraping and recommendation system. Scrapes jobs from multiple boards, filters them with an LLM-based agent, and emails matched jobs to recipients. Runs on GitHub Actions on a cron schedule.

## Commands

```bash
# Setup
uv venv .venv && source .venv/bin/activate && uv pip install -e .

# Run the full pipeline
python main.py

# Tests (live tests require OPENROUTER_API_KEY env var)
pytest tests/
pytest tests/test_summarizer.py -v          # single test file
TEST_MODELS="liquid/lfm-2.5-1.2b-instruct:free" pytest tests/  # specific model

# Linting
ruff check .          # line-length=100, ignores E501
black --check .       # line-length=100, target py310/py311
```

## File Structure

```
main.py                 — Entry point; orchestrates the full pipeline
config.py               — Multi-recipient config, Recipient dataclass, env var loading
scraper.py              — Job scraping via python-jobspy (LinkedIn, Indeed, ZipRecruiter)

filtering/              — Job filtering strategies
├── job_filter.py       — LangGraph agent-based LLM filtering (batch + legacy modes)
├── llm_filter.py       — OpenRouter single-call LLM filter (legacy)
├── llm_filter_legacy.py — Rule-based + LLM filtering (legacy)
└── ai_analyzer.py      — Gemini AI analysis (legacy)

agent/                  — LangGraph workflow (two-level graph)
├── graph.py            — Inner per-job graph: Summarizer → Parallel Analyzer → Voter
├── batch_graph.py      — Outer batch graph: Process All → Batch Reviewer → Human Review
├── state.py            — JobState + BatchState TypedDict definitions
├── nodes/
│   ├── summarizer.py       — Extracts structured job metadata via LLM
│   ├── analyzer.py         — LLM analyzer + deterministic eval + forced CoT + Reflexion feedback
│   ├── reviewer.py         — Rubric-based strict critic with confidence score + gap list
│   ├── batch_reviewer.py   — Samples 10 jobs from batch, threshold 2 disagreements
│   └── human_review.py     — LangGraph interrupt() for CLI human-in-the-loop (uncertain jobs)
├── prompts/
│   ├── summarizer_prompt.py
│   ├── analyzer_prompt.py
│   └── reviewer_prompt.py
└── feedback/
    ├── store.py            — JSONL persistence + create_feedback_store() factory
    ├── vector_store.py     — Milvus Lite vector store for semantic feedback retrieval
    └── human_review_store.py — JSON-based human review decisions, categorized by search term

infra/                  — Shared infrastructure
├── llm_client.py       — AsyncOpenAI + instructor wrapper (OpenRouter), per-call temperature
├── models.py           — Pydantic schemas (JobSummary, JobEvaluation, ReviewResult, BatchReviewResult, etc.)
├── embedding_client.py — sentence-transformers wrapper for local embeddings
└── json_repair.py      — JSON repair utility

tests/
├── conftest.py         — Pytest config & fixtures (@pytest.mark.live for API tests)
├── test_summarizer.py, test_analyzer.py, test_reviewer.py
└── fixtures/           — Test job data
```

## Architecture

**Pipeline flow** (orchestrated in `main.py`):
1. **Scrape** (`scraper.py`) — python-jobspy across LinkedIn, Indeed, ZipRecruiter
2. **Deduplicate** (`storage/database.py`) — SQLite via SQLAlchemy, fallback to text file
3. **LLM Filter** — LangGraph agent (`filtering/job_filter.py` + `agent/`) or legacy
4. **Email** (`notification/email_sender.py`) — Gmail SMTP with per-recipient filtering
5. **Cleanup** (`storage/data_manager.py`) — JSON/CSV storage, auto-deletes files >7 days

**Two-Level LangGraph Architecture (Reflexion):**

Inner graph (per-job, Reflexion loop):
```
[Summarizer] → [Analyzer] → [Reviewer] ──→ END (confidence ≥ 70)
                    ↑             │ (confidence < 70, retry < max)
                    └─────────────┘ (with Gap List feedback)
                    (confidence < 70, retry >= max) → [needs_human_review] → END
```

Outer graph (per-batch):
```
[Process All] → [Batch Reviewer] → [Collect Uncertain] → [Human Review] → [Save Decisions] → END
```

Legacy workflow (USE_LEGACY_WORKFLOW=true): `[Summarizer] → [Analyzer] → [Reviewer] → END`

**Multi-Recipient Architecture** (`config.py`):
- `Recipient` dataclass with email, needs_sponsorship flag, per-recipient search_terms
- `RESULTS_WANTED_MAP` for per-term scrape counts
- Search term groups (slash-separated → multiple queries)

## Key Environment Variables

- `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` — sender credentials
- `RECIPIENTS` — JSON array of `{email, needs_sponsorship, search_terms}` objects
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — LLM access
- `USE_AGENT_WORKFLOW` — `true` for LangGraph agent, `false` for legacy filter
- `USE_LEGACY_WORKFLOW` — `true` for legacy per-job workflow, `false` for Reflexion batch workflow
- `REVIEWER_CONFIDENCE_THRESHOLD` — confidence cutoff for Reviewer (default 70)
- `MAX_ANALYZER_RETRIES` — max retries per job when confidence below threshold (default 1)
- `ENABLE_HUMAN_REVIEW` — CLI human-in-the-loop for uncertain jobs (disable for CI)
- `USE_VECTOR_FEEDBACK` — Milvus vector store for semantic feedback
- `SEARCH_TERMS`, `LOCATIONS`, `HOURS_OLD`, `SITES` — scraping parameters
- `DATABASE_URL` — SQLite path or PostgreSQL URI

See `.env.example` for the full list.

## Code Style

- Python 3.10+, line length 100
- Ruff rules: E, F, I, N, W (E501 ignored)
- Async throughout the LLM filtering pipeline (`asyncio`, `AGENT_CONCURRENCY` batching)
- Rate limiting with exponential backoff for 429s
