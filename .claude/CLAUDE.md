# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Job Hunter Sentinel — an automated job scraping and recommendation system. Scrapes jobs from multiple boards, filters them with an LLM-based agent, and emails matched jobs to recipients. Runs on GitHub Actions on a cron schedule.

## Commands

```bash
# Setup
uv venv .venv && source .venv/bin/activate && uv pip install -e .

# Run the full pipeline
python src/main.py

# Tests (live tests require OPENROUTER_API_KEY env var)
PYTHONPATH=src pytest tests/
PYTHONPATH=src pytest tests/test_summarizer.py -v          # single test file
TEST_MODELS="liquid/lfm-2.5-1.2b-instruct:free" PYTHONPATH=src pytest tests/  # specific model

# Linting
ruff check .          # line-length=100, ignores E501
black --check .       # line-length=100, target py310/py311
```

## File Structure

```
src/
├── main.py                 — Entry point; orchestrates the full pipeline
├── utils/config.py         — Multi-recipient config and search-term grouping helpers
├── infra/
│   ├── scraper.py          — Job scraping via python-jobspy
│   ├── llm_client.py       — AsyncOpenAI + instructor wrapper (OpenRouter)
│   ├── models.py           — Pydantic schemas
│   ├── logging_config.py   — Centralized Loguru setup
│   └── json_repair.py      — JSON repair utility
├── filtering/job_filter.py — LangGraph-driven filtering entrypoint
├── agent/
│   ├── graph.py            — Summarizer -> 3x Analyzer ensemble + majority vote
│   ├── state.py            — TypedDict state for graph execution
│   ├── nodes/              — Summarizer and Analyzer node implementations
│   ├── prompts/            — Prompt templates
│   └── feedback/store.py   — Feedback persistence
├── notification/email_sender.py
└── storage/
    ├── database.py
    └── data_manager.py

tests/
├── conftest.py
├── test_summarizer.py, test_analyzer.py, test_eval.py
└── fixtures/
```

## Architecture

**Pipeline flow** (orchestrated in `src/main.py`):
1. **Scrape** (`src/infra/scraper.py`) — python-jobspy across configured sites
2. **Deduplicate** (`src/storage/database.py`) — SQLite via SQLAlchemy, fallback to text file
3. **LLM Filter** (`src/filtering/job_filter.py`) — per-job LangGraph workflow
4. **Email** (`src/notification/email_sender.py`) — Gmail SMTP with per-recipient filtering
5. **Cleanup** (`src/storage/data_manager.py`) — JSON/CSV storage, auto-deletes files >7 days

**Current LangGraph Architecture (single-job ensemble):**
```
[Summarizer] → [Analyzer x3 in parallel] → [Majority Vote + deterministic overrides] → END
```

- Summarizer node: `src/agent/nodes/summarizer.py`
- Analyzer node: `src/agent/nodes/analyzer.py`
- Graph assembly + voting: `src/agent/graph.py`

**Multi-Recipient Architecture** (`src/utils/config.py`):
- `Recipient` dataclass with email, needs_sponsorship flag, per-recipient search_terms
- `RESULTS_WANTED_MAP` for per-term scrape counts
- Search term groups (slash-separated → multiple queries)

## Key Environment Variables

- `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` — sender credentials
- `RECIPIENTS` — JSON array of `{email, needs_sponsorship, search_terms}` objects
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — LLM access
- `USE_LLM_FILTER` — enable/disable LLM filtering stage
- `LLM_WORKERS` — parallel worker count for filtering (`0` = auto)
- `AGENT_CONCURRENCY` — async job concurrency in the filter workflow
- `USE_VECTOR_FEEDBACK` — enables optional vector feedback init (falls back to JSONL if unavailable)
- `SEARCH_TERMS`, `LOCATIONS`, `HOURS_OLD`, `SITES` — scraping parameters
- `DATABASE_URL` — SQLite path or PostgreSQL URI

See `.env.example` for the full list.

## Code Style

- Python 3.10+, line length 100
- Ruff rules: E, F, I, N, W (E501 ignored)
- Async throughout the LLM filtering pipeline (`asyncio`, `AGENT_CONCURRENCY` batching)
- Rate limiting with exponential backoff for 429s
