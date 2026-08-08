"""
Shared pytest fixtures for the DAWA backend test suite.

Key fixture: `isolate_db` — redirects every test to a fresh temporary SQLite
database so tests never share state with the production DB or each other.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_db(monkeypatch, tmp_path):
    """
    Point DAWA_DB_PATH at a per-test temporary file before each test and
    unset it afterwards.  Because call_store._db_path() reads the env var at
    connection time, no module reload is required — the next connect() call
    automatically uses the fresh path.
    """
    db_file = tmp_path / "test_calls.db"
    monkeypatch.setenv("DAWA_DB_PATH", str(db_file))
    yield
    # monkeypatch restores the env var automatically after yield
