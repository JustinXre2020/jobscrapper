"""Shared fixtures and configuration for prompt tests."""

import os
import sys
from typing import List

import pytest

# Ensure the jobsrapper package root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infra.llm_client import LLMClient  # noqa: E402
from tests.fixtures.jobs import ALL_FIXTURES, FIXTURE_IDS, JobFixture  # noqa: E402

# --- Model parametrization ---

DEFAULT_TEST_MODELS: List[str] = [
    "liquid/lfm-2.5-1.2b-instruct:free",
    "qwen/qwen3-30b-a3b:free",
]


def _get_test_models() -> List[str]:
    """Read test models from TEST_MODELS env var or use defaults."""
    env = os.getenv("TEST_MODELS", "")
    if env.strip():
        return [m.strip() for m in env.split(",") if m.strip()]
    return DEFAULT_TEST_MODELS


# --- Markers ---


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "live: tests that call real OpenRouter API")


# --- Fixtures ---


@pytest.fixture(params=_get_test_models(), scope="session")
def llm_client(request: pytest.FixtureRequest) -> LLMClient:
    """Session-scoped LLMClient parametrized by model.

    Skips if OPENROUTER_API_KEY is not set.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set")
    return LLMClient(model=request.param, api_key=api_key)


@pytest.fixture(params=list(range(len(ALL_FIXTURES))), ids=FIXTURE_IDS)
def job_fixture(request: pytest.FixtureRequest) -> JobFixture:
    """Parametrized fixture returning each job test case."""
    return ALL_FIXTURES[request.param]
