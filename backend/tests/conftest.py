"""Shared test fixtures.

Environment variables are set before any Luxion module is imported so the
settings cache resolves against an isolated temporary data directory.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="luxion-test-"))
os.environ["LUXION_APP__ENVIRONMENT"] = "test"
os.environ["LUXION_APP__DATA_DIR"] = str(_TMP)
os.environ["LUXION_APP__LOGS_DIR"] = str(_TMP)
os.environ["LUXION_DB__URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["LUXION_LOGGING__LEVEL"] = "WARNING"
# Chat tests must not require a running model server.
os.environ["LUXION_LLM__PROVIDER"] = "mock"
os.environ["LUXION_LLM__MODEL"] = ""
os.environ["LUXION_LLM__MOCK_DELAY_S"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def tmp_dir() -> Path:
    return _TMP


@pytest.fixture(scope="session")
def client():
    from luxion.api.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def fresh_provider():
    """Every test starts from a cold provider cache."""
    from luxion.llm.registry import reset_provider

    reset_provider()
    yield
    reset_provider()
