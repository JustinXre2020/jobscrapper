# Copilot Instructions for Job Hunter Sentinel

This file provides guidance for GitHub Copilot when working with this codebase.

## Project Overview

Job Hunter Sentinel — an automated job scraping and recommendation system for O-1 visa applicants. Scrapes jobs from multiple boards, filters them with an LLM-based agent pipeline using LangGraph + Reflexion architecture, and emails matched jobs to recipients. Runs on GitHub Actions once per weekday (1 PM EST), skipping US federal holidays.

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

# Run with specific model(s) — comma-separated; defaults to liquid/lfm-2.5-1.2b-instruct:free and qwen/qwen3-30b-a3b:free
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
3. **LLM Filter** (`src/filtering/job_filter.py`) — LangGraph per-job workflow; writes `data/summarizer_results_{ts}.json` and `data/analyzer_results_{ts}.json` after each run
4. **Email** (`src/notification/email_sender.py`) — Gmail SMTP with per-recipient filtering
5. **Cleanup** (`src/storage/data_manager.py`) — JSON/CSV storage, auto-deletes files >7 days

### Current LangGraph Architecture (Single-Job Ensemble)

**Per-job graph** (`src/agent/graph.py`):
```
[SummarizerNode] → [route_after_summarize] → [AnalyzerNode (x3 in parallel)] → [Majority Vote + deterministic overrides] → END
                                           ↘ END (if skipped or error with no summary)
```

- **SummarizerNode** (`src/agent/nodes/summarizer.py`): Extracts structured job metadata via LLM (`SUMMARIZER_PROVIDER` / `SUMMARIZER_MODEL`). Passed directly to `graph.add_node()` — no wrapper closure.
- **`route_after_summarize()`** (`src/agent/graph.py`): Conditional edge — if `state["skipped"]` is True or there's an error with no summary, routes directly to END (skips Analyzer). Otherwise routes to `"analyzer"`.
- **AnalyzerNode** (`src/agent/nodes/analyzer.py`): Runs 3 parallel LLM calls internally via `asyncio.gather`, applies majority vote across `BOOLEAN_FIELDS`, then applies deterministic overrides. Passed directly to `graph.add_node()` — no wrapper closure.
- Each node extends `BaseNode` and holds its own `BaseLLMClient` instance — swap providers without touching graph logic.
- `BOOLEAN_FIELDS = ["keyword_match", "visa_sponsorship", "entry_level", "requires_phd", "is_internship"]` and helpers `_majority_vote_evaluation`, `_pick_closest_reason` live in `analyzer.py`.
- Before the LLM ensemble, `_deterministic_eval()` runs rule-based logic and returns `None` for fields that need LLM judgment; non-None values override the ensemble result.

### LLMFilter Debug Output
After each `batch_filter_jobs()` call, `LLMFilter._save_agent_results()` writes two JSON files directly to `data/` (independent of `DataManager`):
- `data/summarizer_results_{YYYY-MM-DD_HH-MM}.json` — raw `JobSummaryModel` output per job that had a description
- `data/analyzer_results_{YYYY-MM-DD_HH-MM}.json` — raw evaluation dict per job (all jobs including errored/skipped)

Each record contains `title`, `company`, `job_url`, and the respective `summary` / `evaluation` dict.

Filter stats are logged after each run including a **level breakdown** (`internship=N, entry=N, junior=N, mid=N, senior=N`) for jobs that passed all filters.

### Feedback Stores
- **JSONL** (default): Chronological, last 20 entries (`src/agent/feedback/store.py`)
- Optional vector mode attempts to initialize embedding support and falls back to JSONL if unavailable

### Multi-Recipient Architecture
Defined in `src/utils/config.py`:
- `Recipient` dataclass: `email`, `needs_sponsorship` flag, per-recipient `search_terms`, `accepted_levels` (list of seniority levels to include, defaults to `["entry"]`)
- `SEARCH_TERM_GROUPS`: statically defined dict in `config.py` mapping group name → list of individual queries (e.g. `"business analyst/data analyst"` → `["business analyst", "data analyst"]`); not an env var
- `RESULTS_WANTED_MAP`: per-term scrape count overrides (from `RESULTS_WANTED_MAP` env var, JSON object)
- Legacy fallback: `RECIPIENT_EMAIL` + global `SEARCH_TERMS` env vars

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
│   ├── graph.py            — Per-job graph, conditional routing, analyzer ensemble voting
│   ├── state.py            — JobState TypedDict; AgentState is a backwards-compat alias
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

### Configuration (pydantic-settings)
All environment variables are centralised in `src/utils/config.py` as a `Settings(BaseSettings)` class.
- Import the singleton: `from utils.config import settings`
- **Never** call `os.getenv()` directly anywhere in the codebase
- `.env` path is resolved absolutely from `config.py`'s location (works regardless of cwd)
- Fields use `lower_case`; env vars use `UPPER_CASE` — pydantic-settings maps them automatically

### Async Throughout
- All LLM interactions use `asyncio` and `AsyncOpenAI`
- Parallel job processing controlled by `AGENT_CONCURRENCY` (default 50)
- Rate limiting with exponential backoff for 429s (2s → 4s → 8s)

### Structured Output
- Use Pydantic models + `instructor` for LLM output
- JSON repair as fallback for malformed responses
- Models defined in `src/infra/models.py`: `JobSummary`, `JobEvaluation`, `ReviewResult`, etc.

### Deterministic Overrides
`_deterministic_eval()` in `src/agent/nodes/analyzer.py` runs before the LLM ensemble and returns `None` for fields requiring semantic judgment. Non-None values always override the majority vote:
- `visa_sponsorship`: empty `visa_statements` → `True`; denial phrases (e.g. "must be", "no visa", "without sponsorship", "us citizen") → `False`
- `is_internship`: `True` if summary's `is_internship_coop` is set, or title contains `intern`, `co-op`, `fellowship`, or `apprenticeship`
- `requires_phd`: `True` if summary's `education_required == "phd"`
- `entry_level`: `False` if `seniority_level` is `mid/senior/lead/staff/principal/director/vp`, or `years_experience_required >= 2`; `True` if seniority is `entry`/`intern` with ≤1 year; otherwise `None` (left to LLM)
- `keyword_match`: always `None` — requires semantic judgment, never deterministic

### Testing with Markers
- Use `@pytest.mark.live` for tests hitting real APIs
- These tests require `OPENROUTER_API_KEY` in environment
- Default test models: `liquid/lfm-2.5-1.2b-instruct:free`, `qwen/qwen3-30b-a3b:free`
- Override via `TEST_MODELS` environment variable (comma-separated)

## Critical Environment Variables

All env vars are loaded via **pydantic-settings** (`Settings` class in `src/utils/config.py`).
Never call `os.getenv()` directly — read from the `settings` singleton instead:

```python
from utils.config import settings
print(settings.hours_old)  # typed int
```

The `.env` file path is anchored absolutely to `config.py`'s location, so it is found regardless of the working directory.

See `.env.example` for the full list. Key ones:

**Email Configuration:**
- `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` — sender credentials (App Password, not account password)
- `RECIPIENTS` — JSON array of `{email, needs_sponsorship, search_terms, accepted_levels}` objects

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

**Agent Tuning:**
- `AGENT_CONCURRENCY` — parallel job processing limit (default 50)

**Scraping:**
- `SEARCH_TERMS`, `LOCATIONS`, `HOURS_OLD`, `SITES`, `RESULTS_WANTED` — scraping parameters
- `DATABASE_URL` — SQLite path or PostgreSQL/Supabase URI

**Redis:**
- `REDIS_HOST` — Redis server hostname/IP (stored as GitHub secret)
- `REDIS_PORT` — Redis server port (stored as GitHub secret)

## Code Style

- Python 3.13+, line length 100
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
