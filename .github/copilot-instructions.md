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
python src/main.py

# Test individual modules
python src/infra/scraper.py  # Job scraping only
```

### Testing
```bash
# All tests
PYTHONPATH=src pytest tests/

# Single test file with verbose output
PYTHONPATH=src pytest tests/test_summarizer.py -v

# Only tests hitting real APIs (requires OPENROUTER_API_KEY)
PYTHONPATH=src pytest -m live

# Run with specific model
TEST_MODELS="liquid/lfm-2.5-1.2b-instruct:free" PYTHONPATH=src pytest tests/
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
Orchestrated in `src/main.py`:
1. **Scrape** (`src/infra/scraper.py`) — python-jobspy across configured sites
2. **Deduplicate** (`src/storage/database.py`) — SQLite via SQLAlchemy, fallback to text file
3. **LLM Filter** (`src/filtering/job_filter.py`) — LangGraph per-job workflow
4. **Email** (`src/notification/email_sender.py`) — Gmail SMTP with per-recipient filtering
5. **Cleanup** (`src/storage/data_manager.py`) — JSON/CSV storage, auto-deletes files >7 days

### Current LangGraph Architecture (Single-Job Ensemble)

**Per-job graph** (`src/agent/graph.py`):
```
[Summarizer] → [Analyzer x3 in parallel] → [Majority Vote + deterministic overrides] → END
```

- **Summarizer** (`src/agent/nodes/summarizer.py`): Extracts structured job metadata via LLM (`SUMMARIZER_PROVIDER` / `SUMMARIZER_MODEL`)
- **Analyzer** (`src/agent/nodes/analyzer.py`): Runs LLM evaluation with deterministic override rules (`ANALYZER_PROVIDER` / `ANALYZER_MODEL`)
- **Graph Voting** (`src/agent/graph.py`): Executes 3 analyzer calls and computes majority decision
- Deterministic overrides are applied for explicit signals like sponsorship, internship, and PhD requirements
- Each node holds its own `BaseLLMClient` instance — swap providers without touching graph logic

### Feedback Stores
- **JSONL** (default): Chronological, last 20 entries (`src/agent/feedback/store.py`)
- Optional vector mode attempts to initialize embedding support and falls back to JSONL if unavailable

### Multi-Recipient Architecture
Defined in `src/utils/config.py`:
- `Recipient` dataclass: email, `needs_sponsorship` flag, per-recipient `search_terms`
- `SEARCH_TERM_GROUPS`: slash-separated terms expand to multiple queries
- `RESULTS_WANTED_MAP`: per-term scrape count overrides
- Legacy fallback: `RECIPIENT_EMAIL` + global `SEARCH_TERMS`

### LLM Client
`src/infra/llm_client.py`:
- `BaseLLMClient` (ABC) — interface all nodes depend on; methods: `complete_structured()`, `complete_text()`
- `OpenRouterClient` — AsyncOpenAI via OpenRouter with `instructor` for structured Pydantic output
- `LocalInferenceClient` — targets a local OpenAI-compatible endpoint (e.g. Ollama); no API key required
- `create_llm_client(provider, model)` — factory: `provider="openrouter"` or `"local"`; auto-detects when unset
- `LLMClient` — backwards-compat alias for `OpenRouterClient`
- Per-call temperature override for parallel analyzer diversity
- Retries on 502/503/504 (2x, 5s base delay)
- Falls back to text mode + JSON repair (`src/infra/json_repair.py`) when structured output fails

### BaseNode
`src/agent/nodes/base.py`:
- All agent nodes extend `BaseNode(ABC)` and receive a `BaseLLMClient` at construction time
- Shared helpers: `_job_context(job)` → readable log label; `_structured_with_fallback(messages, model_class)` → structured call with automatic text+JSON repair fallback
- Inject different clients per node for testing or provider switching

## Key Conventions

### File Organization
```
src/
├── main.py                 — Entry point; orchestrates pipeline
├── utils/config.py         — Multi-recipient config, env var loading
├── infra/
│   ├── scraper.py          — Job scraping via python-jobspy
│   ├── llm_client.py       — BaseLLMClient ABC + OpenRouterClient + LocalInferenceClient + factory
│   ├── models.py           — Pydantic schemas
│   ├── logging_config.py   — Loguru configuration
│   └── json_repair.py      — JSON repair for malformed LLM output
├── filtering/job_filter.py — LangGraph filtering entrypoint (builds per-node clients)
├── agent/
│   ├── graph.py            — Per-job graph + analyzer ensemble voting
│   ├── state.py            — JobState TypedDict definitions
│   ├── nodes/
│   │   ├── base.py         — BaseNode ABC with shared helpers
│   │   ├── summarizer.py   — SummarizerNode (uses SUMMARIZER_PROVIDER/MODEL)
│   │   └── analyzer.py     — AnalyzerNode (uses ANALYZER_PROVIDER/MODEL)
│   ├── prompts/            — System prompts
│   └── feedback/store.py   — Feedback persistence
├── storage/
│   ├── database.py         — SQLAlchemy dedup tracking, text-file fallback
│   └── data_manager.py     — JSON/CSV storage, auto-cleanup >7 days
└── notification/email_sender.py — Gmail SMTP dispatcher

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
- Models defined in `src/infra/models.py`: `JobSummary`, `JobEvaluation`, `ReviewResult`, etc.

### Deterministic Overrides
In `src/agent/nodes/analyzer.py`, certain fields have deterministic logic that overrides LLM output:
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
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — OpenRouter access (required only when using OpenRouter provider)
- `LOCAL_LLM_API_URL` — local inference server base URL (default: `http://localhost:11434/v1`)
- `LOCAL_LLM_API_KEY` — key for local server if needed (default: `"local"`)
- `LOCAL_LLM_MODEL` — local model name (default: `"xiaomi"`)

**Per-Node Model Config:**
- `SUMMARIZER_PROVIDER` — `local` or `openrouter` (default: `local`)
- `SUMMARIZER_MODEL` — model name for Summarizer (default: provider default)
- `ANALYZER_PROVIDER` — `local` or `openrouter` (default: `openrouter`)
- `ANALYZER_MODEL` — model name for Analyzer (default: `liquid/lfm-2.2-6b`)

**Workflow Mode:**
- `USE_LLM_FILTER` — enable/disable LLM filtering stage

**Agent Tuning:**
- `LLM_WORKERS` — parallel worker count (`0` = auto)
- `USE_VECTOR_FEEDBACK` — enable optional vector feedback initialization
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
1. Create node file in `src/agent/nodes/`
2. Define a class extending `BaseNode` (`src/agent/nodes/base.py`) with `async def __call__(self, state)`
3. Call `self.llm_client` (a `BaseLLMClient`) for inference; use `self._structured_with_fallback()` for robust structured output
4. Add system prompt in `src/agent/prompts/`
5. Update graph in `src/agent/graph.py`
6. Add tests in `tests/test_[nodename].py` with `@pytest.mark.live`

### Modifying Filtering Logic
- Current: `src/filtering/job_filter.py` + `src/agent/` modules
- Legacy modes available for fallback/comparison

### Changing Email Templates
Edit `src/notification/email_sender.py`:
- `create_email_body()` — overall email structure
- `create_job_html()` — individual job cards

### Updating Scraping Sources
Modify `src/infra/scraper.py`:
- `self.sites` list (must be supported by python-jobspy)
- Adjust `SITES` environment variable

### Database Fallback
If SQLite/Supabase fails, system auto-downgrades to `sent_jobs.txt` text file for deduplication.
