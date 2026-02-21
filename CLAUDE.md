# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Job Hunter Sentinel — an automated job scraping and recommendation system for O-1 visa applicants and general job seekers. Scrapes jobs from multiple boards, filters them with an LLM-based agent pipeline, and emails matched jobs to recipients. Runs on GitHub Actions twice daily (6 AM & 1 PM EST).

## Commands

```bash
# Setup
./setup.sh                                    # one-click: installs uv, creates venv, installs deps
uv venv .venv && source .venv/bin/activate && uv pip install -e .  # manual setup

# Run the full pipeline
python main.py

# Tests (live tests require OPENROUTER_API_KEY)
pytest tests/                                  # all tests
pytest tests/test_summarizer.py -v             # single test file
pytest -m live                                 # only tests hitting real APIs
TEST_MODELS="liquid/lfm-2.5-1.2b-instruct:free" pytest tests/  # specific model

# Linting & formatting
ruff check .                                   # lint (rules: E, F, I, N, W; ignores E501)
black --check .                                # format check (line-length=100, py310/py311)
black .                                        # auto-format
```

## File Structure

```
main.py                 — Entry point; orchestrates the full pipeline
config.py               — Multi-recipient config, Recipient dataclass, env var loading
scraper.py              — Job scraping via python-jobspy (LinkedIn, Indeed, ZipRecruiter, Google)

filtering/              — Job filtering strategies
├── job_filter.py       — LangGraph agent-based LLM filtering (batch + legacy modes)
├── llm_filter.py       — OpenRouter single-call LLM filter (legacy)
├── llm_filter_legacy.py — Rule-based + LLM filtering (legacy)
└── ai_analyzer.py      — Gemini AI analysis (legacy)

agent/                  — LangGraph workflow (two-level graph, Reflexion architecture)
├── graph.py            — Inner per-job graph: Summarizer → Analyzer ↔ Reviewer (Reflexion loop)
├── batch_graph.py      — Outer batch graph: Process All → Batch Reviewer → Collect Uncertain → Human Review → Save Decisions
├── state.py            — JobState + BatchState TypedDict definitions
├── nodes/
│   ├── summarizer.py       — Extracts structured job metadata via LLM
│   ├── analyzer.py         — LLM analyzer + deterministic eval + forced CoT + Reflexion feedback
│   ├── reviewer.py         — Rubric-based strict critic with confidence score + gap list
│   ├── batch_reviewer.py   — Samples 10 jobs from batch, threshold 2 disagreements
│   └── human_review.py     — LangGraph interrupt() for CLI human-in-the-loop (uncertain jobs)
├── prompts/            — System prompts for each node
└── feedback/
    ├── store.py            — JSONL persistence + create_feedback_store() factory
    ├── vector_store.py     — Milvus Lite vector store for semantic feedback retrieval
    └── human_review_store.py — JSON-based human review decisions, categorized by search term

infra/                  — Shared infrastructure
├── llm_client.py       — AsyncOpenAI + instructor wrapper (OpenRouter), per-call temperature
├── models.py           — Pydantic schemas (JobSummary, JobEvaluation, ReviewResult, BatchReviewResult, etc.)
├── embedding_client.py — sentence-transformers wrapper for local embeddings
└── json_repair.py      — JSON repair for malformed LLM output

storage/
├── database.py         — SQLAlchemy dedup tracking (SentJob model), text-file fallback
└── data_manager.py     — JSON/CSV storage, auto-cleanup of files >7 days

notification/
└── email_sender.py     — Gmail SMTP dispatcher, per-recipient HTML emails

tests/
├── conftest.py         — Pytest config, fixtures, model parametrization (@pytest.mark.live)
├── test_summarizer.py, test_analyzer.py, test_reviewer.py
└── fixtures/           — Test job data
```

## Architecture

**Pipeline flow** (orchestrated in `main.py`):
1. **Scrape** (`scraper.py`) — python-jobspy across multiple job boards
2. **Deduplicate** (`storage/database.py`) — SQLite via SQLAlchemy, fallback to text file
3. **LLM Filter** — LangGraph agent (`filtering/job_filter.py` + `agent/`) or legacy (`filtering/llm_filter.py`) based on `USE_AGENT_WORKFLOW`
4. **Email** (`notification/email_sender.py`) — Gmail SMTP with per-recipient filtering
5. **Cleanup** (`storage/data_manager.py`) — JSON/CSV storage, auto-deletes files >7 days

**Two-Level LangGraph Architecture (Reflexion):**

Inner graph (per-job, `agent/graph.py`) — Reflexion loop:
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
- Analyzer uses forced Chain-of-Thought reasoning before JSON output
- Reviewer is a strict rubric-based critic producing confidence score (0-100) + gap list
- Deterministic overrides for unambiguous fields (visa, internship, PhD, clear seniority)
- On retry: Analyzer receives structured gap list feedback for Reflexion-style self-correction
- Exhausted retries: job flagged `needs_human_review=True` for human intervention

Outer graph (per-batch, `agent/batch_graph.py`):
```
[Process All Jobs] → [Batch Reviewer] → [Collect Uncertain] → [Human Review] → [Save Decisions] → END
       ↑                                                              |
       +---- (2+ disagreements, redo < max) --------------------------+
```
- Batch reviewer samples 10 jobs, threshold 2 disagreements
- Collect uncertain: gathers jobs where `needs_human_review=True` from inner graph
- Human review via LangGraph `interrupt()`: presents both batch disagreements and uncertain jobs
- Save decisions: persists human decisions to `data/human_review_results.json` (by search term) and feedback store
- In CI mode (`ENABLE_HUMAN_REVIEW=false`): uncertain jobs auto-accepted with warning log

**Legacy workflow** (USE_LEGACY_WORKFLOW=true):
```
[Summarizer] → [Analyzer] → [Reviewer] → END
                   ↑              ↓ (if rejected)
                   └──────────────┘ (max 1 retry)
```

**Feedback Stores:**
- JSONL (default): chronological, last 20 entries
- Milvus vector (USE_VECTOR_FEEDBACK=true): semantic search via sentence-transformers embeddings
- Human review results (`data/human_review_results.json`): categorized by search term, loaded as high-confidence reference examples

**Multi-Recipient Architecture** (`config.py`):
- `Recipient` dataclass: email, `needs_sponsorship` flag, per-recipient `search_terms`
- `SEARCH_TERM_GROUPS`: slash-separated terms expand to multiple queries
- `RESULTS_WANTED_MAP`: per-term scrape count overrides
- Legacy fallback: `RECIPIENT_EMAIL` + global `SEARCH_TERMS`

**LLM Client** (`infra/llm_client.py`):
- AsyncOpenAI via OpenRouter with `instructor` for structured Pydantic output
- Per-call temperature override for parallel analyzer diversity
- Retries on 502/503/504 (2x, 5s base delay)
- Falls back to text mode + JSON repair when structured output fails

## Key Environment Variables

See `.env.example` for the full list. Critical ones:

- `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` — sender credentials (App Password, not account password)
- `RECIPIENTS` — JSON array of `{email, needs_sponsorship, search_terms}` objects
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — LLM access
- `USE_AGENT_WORKFLOW` — `true` for LangGraph agent, `false` for legacy filter
- `USE_LEGACY_WORKFLOW` — `true` for legacy per-job workflow, `false` for Reflexion batch workflow
- `REVIEWER_CONFIDENCE_THRESHOLD` — confidence cutoff for Reviewer pass/fail (default 70)
- `MAX_ANALYZER_RETRIES` — max Analyzer retries per job when confidence below threshold (default 1)
- `ENABLE_HUMAN_REVIEW` — `true` for CLI human-in-the-loop for uncertain jobs (disable for CI)
- `USE_VECTOR_FEEDBACK` — `true` for Milvus vector feedback store
- `AGENT_CONCURRENCY` — parallel job processing limit (default 5)
- `SEARCH_TERMS`, `LOCATIONS`, `HOURS_OLD`, `SITES`, `RESULTS_WANTED` — scraping parameters
- `DATABASE_URL` — SQLite path or PostgreSQL/Supabase URI

## Code Style

- Python 3.10+, line length 100
- Ruff rules: E, F, I, N, W (E501 ignored)
- Black: line-length=100, target py310/py311
- Async throughout the LLM pipeline (`asyncio`, `AsyncOpenAI`)
- Rate limiting with exponential backoff for 429s (2s → 4s → 8s)
- Structured output via Pydantic models + `instructor`; JSON repair as fallback
