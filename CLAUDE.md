# CLAUDE.md — Job Hunter Sentinel

This file provides guidance for Claude when working with this codebase.

## Project Overview

Job Hunter Sentinel — an automated job scraping and recommendation system for O-1 visa applicants. Scrapes jobs from multiple boards, filters them with an LLM-based agent pipeline using LangGraph, and emails matched jobs to recipients. Runs on GitHub Actions once per weekday (1 PM EST), skipping US federal holidays.

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

# Run with specific model(s) — comma-separated
TEST_MODELS="liquid/lfm-2.5-1.2b-instruct:free" PYTHONPATH=src pytest tests/
```

### Linting & Formatting
```bash
ruff check .        # Lint (rules: E, F, I, N, W; ignores E501)
black --check .     # Format check
black .             # Auto-format
```

## High-Level Architecture

### Pipeline Flow
Orchestrated in `src/main.py`:
1. **Scrape** (`src/infra/scraper.py`) — python-jobspy across configured sites
2. **Deduplicate** (`src/storage/database.py`) — SQLite via SQLAlchemy, fallback to text file
3. **LLM Filter** (`src/filtering/job_filter.py`) — LangGraph per-job workflow; writes `data/summarizer_results_{ts}.json` and `data/analyzer_results_{ts}.json` after each run
4. **Email** (`src/notification/email_sender.py`) — Gmail SMTP with per-recipient filtering
5. **Cleanup** (`src/storage/data_manager.py`) — JSON/CSV storage, auto-deletes files >7 days

### LangGraph Architecture (Single-Job Ensemble)

**Per-job graph** (`src/agent/graph.py`):
```
[SummarizerNode] → [route_after_summarize] → [AnalyzerNode (x3 in parallel)] → [Majority Vote + deterministic overrides] → END
                                           ↘ END (if skipped or error with no summary)
```

- **SummarizerNode** (`src/agent/nodes/summarizer.py`): Extracts structured `JobSummaryModel` from raw posting via LLM (`SUMMARIZER_PROVIDER` / `SUMMARIZER_MODEL`).
- **`route_after_summarize()`**: Conditional edge — routes to END if `state["skipped"]` or error with no summary; otherwise routes to `"analyzer"`.
- **AnalyzerNode** (`src/agent/nodes/analyzer.py`): Runs 3 parallel LLM calls via `asyncio.gather`, applies majority vote across `BOOLEAN_FIELDS`, then applies deterministic overrides.
- Each node extends `BaseNode` and holds its own `BaseLLMClient` — swap providers without touching graph logic.
- `BOOLEAN_FIELDS = ["keyword_match", "visa_sponsorship", "entry_level", "requires_phd", "is_internship"]`
- `_deterministic_eval()` runs before the LLM ensemble; returns `None` for fields needing LLM judgment; non-`None` values always override the majority vote.

### LLMFilter Debug Output
After each `batch_filter_jobs()` call, `LLMFilter._save_agent_results()` writes two JSON files directly to `data/` (independent of `DataManager`):
- `data/summarizer_results_{YYYY-MM-DD_HH-MM}.json` — raw `JobSummaryModel` per job that had a description
- `data/analyzer_results_{YYYY-MM-DD_HH-MM}.json` — raw evaluation dict per job (all jobs including errored/skipped)

Each record: `{title, company, job_url, summary|evaluation}`.

Filter stats logged after each run include a **level breakdown** (`internship=N, entry=N, junior=N, mid=N, senior=N`).

### Multi-Recipient Architecture
Defined in `src/utils/config.py`:
- `Recipient` dataclass: `email`, `needs_sponsorship`, `search_terms`, `accepted_job_levels` (defaults to `["entry"]`)
- `SEARCH_TERM_GROUPS`: **statically defined** dict in `config.py` — not an env var. Maps group name → list of queries (e.g. `"business analyst/data analyst"` → `["business analyst", "data analyst"]`)
- `RESULTS_WANTED_MAP`: per-term scrape count overrides (JSON env var)
- Legacy fallback: `RECIPIENT_EMAIL` + global `SEARCH_TERMS` env vars

### LLM Client
`src/infra/llm_client.py`:
- `BaseLLMClient` (ABC): `complete_structured()`, `complete_text()`
- `OpenRouterClient` — AsyncOpenAI via OpenRouter + `instructor` for Pydantic output
- `LocalInferenceClient` — local OpenAI-compatible endpoint (e.g. Ollama); no API key required
- `create_llm_client(provider, model)` — factory; `provider="openrouter"` or `"local"`
- `LLMClient` — backwards-compat alias for `OpenRouterClient`
- Retries on 502/503/504 (2×, 5 s base delay); falls back to text + JSON repair on structured failure

### BaseNode
`src/agent/nodes/base.py`:
- All nodes extend `BaseNode(ABC)`, receive `BaseLLMClient` at construction
- `_job_context(job)` → `"Title @ Company"` log label
- `_structured_with_fallback(messages, model_class)` → structured call with text+JSON repair fallback

## Key Conventions

### Configuration (pydantic-settings)
All env vars live in `Settings(BaseSettings)` in `src/utils/config.py`.
- **Always** import the singleton: `from utils.config import settings`
- **Never** call `os.getenv()` directly anywhere in the codebase
- `.env` path anchored absolutely to `config.py`'s location — works regardless of cwd
- Fields `lower_case`; env vars `UPPER_CASE` — pydantic-settings maps automatically

### Async Throughout
- All LLM interactions use `asyncio` + `AsyncOpenAI`
- `AGENT_CONCURRENCY` (default 50) controls parallel job processing
- Rate limiting with exponential backoff for 429s

### Structured Output
- Pydantic models + `instructor` for LLM output; JSON repair as fallback
- Models in `src/infra/models.py`: `JobSummaryModel`, `JobEvaluation`, etc.
- `job_level`: `Literal["internship", "entry", "junior", "mid", "senior"]` — used by `email_sender.py` for per-recipient `accepted_job_levels` filtering

### Deterministic Overrides in Analyzer
`_deterministic_eval()` returns `None` for fields requiring semantic judgment:
- `visa_sponsorship`: empty `visa_statements` → `True`; denial phrases → `False`
- `is_internship`: from `is_internship_coop` flag or title keywords
- `requires_phd`: from `education_required == "phd"`
- `entry_level`: deterministic for clear seniority/years signals; `None` otherwise
- `keyword_match`: always `None` — always left to LLM

### Testing
- `@pytest.mark.live` for tests hitting real APIs (requires `OPENROUTER_API_KEY`)
- Default models: `liquid/lfm-2.5-1.2b-instruct:free`, `qwen/qwen3-30b-a3b:free`
- Override via `TEST_MODELS` env var (comma-separated)
- `asyncio_mode = "auto"` in `pyproject.toml` — no `@pytest.mark.asyncio` needed

### Code Style
- Python 3.13+, line length 100
- Ruff rules: E, F, I, N, W (E501 ignored)
- Black: line-length=100, target py310/py311
- Loguru for all logging (`logger.info`, `logger.warning`, etc.)

## Critical Environment Variables

**Email:**
- `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` — App Password, not account password
- `RECIPIENTS` — JSON array: `[{email, needs_sponsorship, search_terms, accepted_job_levels}]`

**LLM:**
- `OPENROUTER_API_KEY` — required for OpenRouter provider
- `LOCAL_LLM_API_URL` — local server base URL (default: `http://localhost:11434/v1`)
- `SUMMARIZER_PROVIDER` / `SUMMARIZER_MODEL` — defaults: `local` / provider default
- `ANALYZER_PROVIDER` / `ANALYZER_MODEL` — defaults: `openrouter` / `liquid/lfm-2.2-6b`
- `AGENT_CONCURRENCY` — parallel job limit (default 50)

**Scraping:**
- `LOCATIONS`, `HOURS_OLD`, `SITES`, `RESULTS_WANTED`, `DATABASE_URL`

**Redis:**
- `REDIS_HOST`, `REDIS_PORT`

## Common Tasks

### Adding a New Agent Node
1. Create `src/agent/nodes/{name}.py`, extend `BaseNode` with `async def __call__(self, state: JobState)`
2. Use `self._structured_with_fallback()` for robust structured output
3. Add system prompt in `src/agent/prompts/`
4. Wire into graph in `src/agent/graph.py`
5. Add test `tests/test_{name}.py` with `@pytest.mark.live`

### Changing Email Templates
- `create_email_body()` — overall structure
- `create_job_html()` — individual job cards
Both in `src/notification/email_sender.py`.

### Updating Scraping Sources
`src/infra/scraper.py` — modify `self.sites` list (must be supported by python-jobspy).

### Database Fallback
SQLite/Supabase failure → auto-downgrade to `sent_jobs.txt` text file for deduplication.
