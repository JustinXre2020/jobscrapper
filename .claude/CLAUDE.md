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
Root Python files (pipeline stages):
├── main.py                 — Entry point; orchestrates the full pipeline
├── config.py               — Multi-recipient config, Recipient dataclass, env var loading
├── scraper.py              — Job scraping via python-jobspy (LinkedIn, Indeed, ZipRecruiter)
├── database.py             — SQLite/SQLAlchemy dedup tracking (SentJob model), text-file fallback
├── job_filter.py           — LangGraph agent-based LLM filtering (current)
├── llm_filter.py           — OpenRouter LLM filtering (intermediate)
├── llm_filter_legacy.py    — Legacy rule-based + LLM filtering
├── ai_analyzer.py          — Legacy Gemini AI analysis
├── email_sender.py         — Gmail SMTP dispatcher, per-recipient HTML emails
└── data_manager.py         — JSON/CSV storage, auto-cleanup of files >7 days

agent/                      — LangGraph 3-node workflow
├── graph.py                — Workflow orchestration (Summarizer→Analyzer→Reviewer)
├── state.py                — TypedDict agent state definition
├── nodes/
│   ├── summarizer.py       — Extracts structured job metadata
│   ├── analyzer.py         — Evaluates job fitness (visa, seniority, keywords)
│   └── reviewer.py         — QA checks at 20% sample rate, loops back to Analyzer if rejected
├── prompts/
│   ├── summarizer_prompt.py
│   ├── analyzer_prompt.py
│   └── reviewer_prompt.py
└── feedback/
    └── store.py            — Accumulates reviewer corrections across runs

infra/                      — Shared infrastructure
├── llm_client.py           — AsyncOpenAI + instructor wrapper (OpenRouter)
├── models.py               — Pydantic schemas for structured LLM output
└── json_repair.py          — JSON repair utility

tests/
├── conftest.py             — Pytest config & fixtures (@pytest.mark.live for API tests)
├── test_summarizer.py
├── test_analyzer.py
├── test_reviewer.py
└── fixtures/
    └── jobs.py             — Test job data
```

## Architecture

**Pipeline flow** (orchestrated in `main.py`):
1. **Scrape** (`scraper.py`) — python-jobspy across LinkedIn, Indeed, ZipRecruiter
2. **Deduplicate** (`database.py`) — SQLite via SQLAlchemy, fallback to text file
3. **LLM Filter** — either LangGraph agent (`job_filter.py` + `agent/`) or legacy (`llm_filter.py`)
4. **Email** (`email_sender.py`) — Gmail SMTP with per-recipient filtering
5. **Cleanup** (`data_manager.py`) — JSON/CSV storage, auto-deletes files >7 days

**LangGraph Agent** (`agent/`):
```
[Summarizer] → [Analyzer] → [Reviewer (20% sample)] → END
                   ↑              ↓ (if rejected)
                   └──────────────┘
```

**Multi-Recipient Architecture** (`config.py`):
- `Recipient` dataclass with email, needs_sponsorship flag, per-recipient search_terms
- `RESULTS_WANTED_MAP` for per-term scrape counts
- Search term groups (slash-separated → multiple queries)

## Key Environment Variables

- `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` — sender credentials
- `RECIPIENTS` — JSON array of `{email, needs_sponsorship, search_terms}` objects
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — LLM access
- `USE_AGENT_WORKFLOW` — `true` for LangGraph agent, `false` for legacy filter
- `SEARCH_TERMS`, `LOCATIONS`, `HOURS_OLD`, `SITES` — scraping parameters
- `DATABASE_URL` — SQLite path or PostgreSQL URI

See `.env.example` for the full list.

## Code Style

- Python 3.10+, line length 100
- Ruff rules: E, F, I, N, W (E501 ignored)
- Async throughout the LLM filtering pipeline (`asyncio`, `AGENT_CONCURRENCY` batching)
- Rate limiting with exponential backoff for 429s
