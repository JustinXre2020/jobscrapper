# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Job Hunter Sentinel — an automated job scraping and recommendation system. Scrapes jobs from multiple boards, filters them with an LLM-based agent, and emails matched jobs to recipients. Runs on GitHub Actions once per weekday (1 PM EST), skipping US federal holidays.

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
├── utils/config.py         — Settings(BaseSettings) singleton; all env vars in one place
├── infra/
│   ├── scraper.py          — Job scraping via python-jobspy
│   ├── llm_client.py       — BaseLLMClient ABC + OpenRouterClient + LocalInferenceClient + factory
│   ├── models.py           — Pydantic schemas
│   ├── logging_config.py   — Centralized Loguru setup
│   └── json_repair.py      — JSON repair utility
├── filtering/job_filter.py — LangGraph-driven filtering entrypoint
├── agent/
│   ├── graph.py            — build_graph(); passes SummarizerNode + AnalyzerNode directly to add_node()
│   ├── state.py            — TypedDict state for graph execution
│   ├── nodes/
│   │   ├── base.py         — BaseNode ABC with shared helpers (_job_context, _structured_with_fallback)
│   │   ├── summarizer.py   — SummarizerNode (SUMMARIZER_PROVIDER/MODEL)
│   │   └── analyzer.py     — AnalyzerNode (3x ensemble, majority vote, deterministic overrides)
│   ├── prompts/            — Prompt templates
│   └── feedback/store.py   — Feedback persistence
├── notification/email_sender.py
└── storage/
    ├── database.py
    └── data_manager.py

tests/
├── conftest.py
├── test_summarizer.py, test_analyzer.py, test_eval.py
├── eval_report.py          — Standalone eval runner; uses settings singleton
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
[SummarizerNode] → [AnalyzerNode (x3 in parallel)] → [Majority Vote + deterministic overrides] → END
```

- `SummarizerNode` and `AnalyzerNode` are passed **directly** to `graph.add_node()` — no wrapper closures
- `AnalyzerNode.__call__` runs 3 parallel `_call_llm_analyzer` calls via `asyncio.gather`, majority votes across `BOOLEAN_FIELDS`, then applies deterministic overrides
- `BOOLEAN_FIELDS`, `ANALYZER_TEMPERATURES`, `_majority_vote_evaluation`, `_pick_closest_reason` all live in `analyzer.py`
- Each node extends `BaseNode(ABC)` and receives a `BaseLLMClient` at construction time

**Multi-Recipient Architecture** (`src/utils/config.py`):
- `Recipient` dataclass with email, needs_sponsorship flag, per-recipient search_terms
- `RESULTS_WANTED_MAP` for per-term scrape counts
- Search term groups (slash-separated → multiple queries)

## Configuration (pydantic-settings)

All env vars are centralised in `src/utils/config.py` as `Settings(BaseSettings)`.

```python
from utils.config import settings
print(settings.hours_old)       # typed int, default 24
print(settings.redis_host)      # Optional[str]
```

- **Never call `os.getenv()` directly** — always read from the `settings` singleton
- `.env` path is resolved absolutely using `Path(__file__).parent.parent.parent / ".env"` — works regardless of cwd
- Fields: `lower_case`; env vars: `UPPER_CASE` — pydantic-settings maps them automatically

## Key Environment Variables

- `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` — sender credentials
- `RECIPIENTS` — JSON array of `{email, needs_sponsorship, search_terms}` objects
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — LLM access (OpenRouter)
- `LOCAL_LLM_API_URL` / `LOCAL_LLM_API_KEY` / `LOCAL_LLM_MODEL` — local inference server
- `SUMMARIZER_PROVIDER` / `SUMMARIZER_MODEL` — per-node model routing
- `ANALYZER_PROVIDER` / `ANALYZER_MODEL` — per-node model routing
- `USE_LLM_FILTER` — enable/disable LLM filtering stage
- `LLM_WORKERS` — parallel worker count for filtering (`0` = auto)
- `AGENT_CONCURRENCY` — async job concurrency in the filter workflow (default 50)
- `USE_VECTOR_FEEDBACK` — enables optional vector feedback init (falls back to JSONL if unavailable)
- `SEARCH_TERMS`, `LOCATIONS`, `HOURS_OLD`, `SITES` — scraping parameters
- `DATABASE_URL` — SQLite path or PostgreSQL URI
- `REDIS_HOST` / `REDIS_PORT` — remote Redis server (stored as GitHub secrets)

See `.env.example` for the full list.

## Code Style

- Python 3.10+, line length 100
- Ruff rules: E, F, I, N, W (E501 ignored)
- Async throughout the LLM filtering pipeline (`asyncio`, `AGENT_CONCURRENCY` batching)
- Rate limiting with exponential backoff for 429s
