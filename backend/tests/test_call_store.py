"""
Tests for the persistent call store (SQLite backend).

These tests verify that call records survive a simulated server restart
by reinitialising the store against the same database file.

All tests run against a temporary per-test database (see conftest.py isolate_db).
"""

from __future__ import annotations

import os

import pytest

from app.services.call_store import (
    append_call,
    get_all_calls,
    get_call_ids,
    init_db,
    update_call_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reinit() -> None:
    """Re-run init_db() to simulate a server restart against the same file."""
    init_db()


# ---------------------------------------------------------------------------
# Basic read / write
# ---------------------------------------------------------------------------

def test_empty_store_returns_empty_list():
    """A fresh database returns an empty call list."""
    init_db()
    assert get_all_calls() == []


def test_append_and_retrieve():
    """A record written with append_call() must appear in get_all_calls()."""
    init_db()
    append_call(
        log_id="log-001",
        call_id="call-001",
        medication="Metformin",
        phone_masked="+92XXXXX4567",
    )
    records = get_all_calls()
    assert len(records) == 1
    r = records[0]
    assert r["logId"] == "log-001"
    assert r["callId"] == "call-001"
    assert r["medication"] == "Metformin"
    assert r["phoneMasked"] == "+92XXXXX4567"
    assert r["status"] == "dispatched"
    assert "dispatchedAt" in r


def test_records_survive_reinit():
    """
    Call records written before a server restart must still be readable
    after re-initialising the database (i.e., they are truly persistent).
    """
    init_db()
    append_call(log_id="log-restart", call_id="call-restart", medication="Aspirin")

    # Simulate restart — call init_db() again (idempotent) then read
    _reinit()
    records = get_all_calls()
    assert any(r["logId"] == "log-restart" for r in records), (
        "Record was lost after simulated server restart."
    )


def test_most_recent_first():
    """get_all_calls() must return records with the most recent first."""
    import time
    init_db()
    append_call(log_id="log-A", call_id="call-A", medication="DrugA")
    time.sleep(0.01)  # ensure distinct timestamps
    append_call(log_id="log-B", call_id="call-B", medication="DrugB")

    records = get_all_calls()
    ids = [r["logId"] for r in records]
    assert ids.index("log-B") < ids.index("log-A"), (
        "Most-recent record must come first."
    )


def test_limit_is_respected():
    """get_all_calls(limit=N) must return at most N records."""
    init_db()
    for i in range(5):
        append_call(log_id=f"log-{i}", call_id=f"call-{i}", medication="Drug")
    assert len(get_all_calls(limit=3)) == 3


def test_duplicate_log_id_ignored():
    """Inserting the same log_id twice must not raise and must not duplicate the record."""
    init_db()
    append_call(log_id="log-dup", call_id="call-dup", medication="Drug")
    append_call(log_id="log-dup", call_id="call-dup", medication="Drug")
    records = [r for r in get_all_calls() if r["logId"] == "log-dup"]
    assert len(records) == 1


# ---------------------------------------------------------------------------
# Status update
# ---------------------------------------------------------------------------

def test_update_call_status():
    """update_call_status() must change the stored status for matching callId."""
    init_db()
    append_call(log_id="log-upd", call_id="call-upd", medication="Paracetamol")
    update_call_status("call-upd", "completed")
    records = get_all_calls()
    entry = next(r for r in records if r["callId"] == "call-upd")
    assert entry["status"] == "completed"


# ---------------------------------------------------------------------------
# get_call_ids helper
# ---------------------------------------------------------------------------

def test_get_call_ids_returns_set():
    """get_call_ids() must return the set of callIds in the store."""
    init_db()
    append_call(log_id="log-ids-1", call_id="call-ids-1", medication="Drug")
    append_call(log_id="log-ids-2", call_id="call-ids-2", medication="Drug")
    ids = get_call_ids()
    assert "call-ids-1" in ids
    assert "call-ids-2" in ids
