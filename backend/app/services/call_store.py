"""
Persistent call log store for DAWA — backed by SQLite.

All dispatched calls are written here so call history survives server restarts.
The database file lives at backend/data/calls.db (created automatically).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("dawa.call_store")

# ---------------------------------------------------------------------------
# Database path — configurable via DAWA_DB_PATH env var for test isolation.
# Falls back to backend/data/calls.db relative to this file.
# ---------------------------------------------------------------------------

_DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "calls.db"


def _db_path() -> Path:
    """Return the active database path (reads env var at call time for test isolation)."""
    import os
    override = os.environ.get("DAWA_DB_PATH")
    if override:
        return Path(override)
    return _DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    """Open a connection with row_factory set to return dicts."""
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the calls table if it does not exist (idempotent)."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calls (
                log_id        TEXT PRIMARY KEY,
                call_id       TEXT NOT NULL,
                medication    TEXT NOT NULL,
                phone_masked  TEXT NOT NULL DEFAULT '',
                dispatched_at TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'dispatched'
            )
            """
        )
        conn.commit()
    logger.info("CALL_STORE_READY", extra={"db": str(_db_path())})


def append_call(
    log_id: str,
    call_id: str,
    medication: str,
    phone_masked: str = "",
) -> None:
    """Insert a new call record into the persistent store."""
    dispatched_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO calls
                (log_id, call_id, medication, phone_masked, dispatched_at, status)
            VALUES (?, ?, ?, ?, ?, 'dispatched')
            """,
            (log_id, call_id, medication, phone_masked, dispatched_at),
        )
        conn.commit()
    logger.info(
        "CALL_STORE_APPENDED",
        extra={"logId": log_id, "callId": call_id, "medication": medication},
    )


def update_call_status(call_id: str, status: str) -> None:
    """Update the status of an existing call record by callId."""
    with _connect() as conn:
        conn.execute(
            "UPDATE calls SET status = ? WHERE call_id = ?",
            (status, call_id),
        )
        conn.commit()


def get_all_calls(limit: int = 50) -> list[dict[str, Any]]:
    """
    Return call records from the persistent store, most-recent first.

    Returns a list of dicts with camelCase keys to match the existing API contract.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT log_id, call_id, medication, phone_masked, dispatched_at, status
            FROM calls
            ORDER BY dispatched_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "logId": row["log_id"],
            "callId": row["call_id"],
            "medication": row["medication"],
            "phoneMasked": row["phone_masked"],
            "dispatchedAt": row["dispatched_at"],
            "status": row["status"],
        }
        for row in rows
    ]


def get_call_ids(limit: int = 50) -> set[str]:
    """Return the set of callIds present in the local store (for merging)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT call_id FROM calls ORDER BY dispatched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {row["call_id"] for row in rows}
