"""
DAWA P1 persistent store.

Tables (all in the same SQLite file as the P0-A calls table):
  patients         — demo patient profile (razia-bibi)
  medications      — medications per patient
  medication_cues  — caregiver-verified visual recognition cues
  dose_events      — call dispatch record + telephony lifecycle
  escalations      — safety escalation records
  patient_memory   — patient nicknames / aliases (separate from clinical truth)

All seed operations are idempotent (INSERT OR IGNORE).
Access the DB via the same DAWA_DB_PATH env var as call_store.py.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# DB path (shared with call_store.py)
# ---------------------------------------------------------------------------

def _db_path() -> Path:
    env = os.environ.get("DAWA_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data" / "calls.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_dawa_db() -> None:
    """Create all P1/P2 tables and migrate schema if they do not already exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS patients (
                id                TEXT PRIMARY KEY,
                name              TEXT NOT NULL,
                preferred_address TEXT NOT NULL,
                language          TEXT NOT NULL DEFAULT 'ur',
                literacy_mode     TEXT NOT NULL DEFAULT 'voice_first'
            );

            CREATE TABLE IF NOT EXISTS medications (
                id               TEXT PRIMARY KEY,
                patient_id       TEXT NOT NULL REFERENCES patients(id),
                clinical_name    TEXT NOT NULL,
                dosage           TEXT NOT NULL,
                dose_instruction TEXT NOT NULL,
                food_instruction TEXT NOT NULL DEFAULT 'none',
                schedule_time    TEXT NOT NULL,
                routine_anchor   TEXT NOT NULL,
                nickname         TEXT
            );

            CREATE TABLE IF NOT EXISTS medication_cues (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                medication_id TEXT NOT NULL REFERENCES medications(id),
                cue_key       TEXT NOT NULL,
                cue_value     TEXT NOT NULL,
                UNIQUE(medication_id, cue_key)
            );

            CREATE TABLE IF NOT EXISTS dose_events (
                id                TEXT PRIMARY KEY,
                patient_id        TEXT NOT NULL REFERENCES patients(id),
                medication_id     TEXT NOT NULL REFERENCES medications(id),
                scheduled_time    TEXT NOT NULL,
                call_id           TEXT,
                call_status       TEXT NOT NULL DEFAULT 'scheduled',
                adherence_outcome TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS escalations (
                id            TEXT PRIMARY KEY,
                patient_id    TEXT NOT NULL,
                dose_event_id TEXT,
                reason        TEXT NOT NULL,
                detail        TEXT,
                created_at    TEXT NOT NULL,
                resolved_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS patient_memory (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id   TEXT NOT NULL,
                memory_key   TEXT NOT NULL,
                memory_value TEXT NOT NULL,
                UNIQUE(patient_id, memory_key)
            );
        """)

        # ── P2 schema migration — safe to run on every startup ──────────────
        # Add columns that didn't exist in P1.  SQLite raises OperationalError
        # if a column already exists; we catch and ignore it.
        for _alter in [
            "ALTER TABLE dose_events ADD COLUMN schedule_key TEXT",
            "ALTER TABLE dose_events ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                conn.execute(_alter)
            except sqlite3.OperationalError:
                pass  # column already exists

        # Unique index on schedule_key prevents duplicate auto-scan events
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_dose_events_schedule_key
               ON dose_events(schedule_key)
               WHERE schedule_key IS NOT NULL"""
        )


# ---------------------------------------------------------------------------
# Seed data — idempotent demo patient
# ---------------------------------------------------------------------------

def seed_demo_data() -> None:
    """
    Insert the demo patient, medications, cues, and memory.
    Safe to call multiple times (INSERT OR IGNORE).

    Razia Bibi has two white-boxed medications — the signature ambiguity demo:
      metformin-500  (raat wali goli)  — white box, BLUE stripe
      amlodipine-5   (BP wali goli)   — white box, RED stripe
    """
    with _connect() as conn:
        # Patient
        conn.execute(
            """INSERT OR IGNORE INTO patients
               (id, name, preferred_address, language, literacy_mode)
               VALUES (?, ?, ?, ?, ?)""",
            ("razia-bibi", "Razia Bibi", "Ammi", "ur", "voice_first"),
        )

        # Medications
        conn.execute(
            """INSERT OR IGNORE INTO medications
               (id, patient_id, clinical_name, dosage, dose_instruction,
                food_instruction, schedule_time, routine_anchor, nickname)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "metformin-500", "razia-bibi", "Metformin", "500 mg",
                "1 tablet", "after dinner", "21:00", "after dinner", "raat wali goli",
            ),
        )
        conn.execute(
            """INSERT OR IGNORE INTO medications
               (id, patient_id, clinical_name, dosage, dose_instruction,
                food_instruction, schedule_time, routine_anchor, nickname)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "amlodipine-5", "razia-bibi", "Amlodipine", "5 mg",
                "1 tablet", "none", "08:00", "morning", "BP wali goli",
            ),
        )

        # Verified recognition cues — BOTH packages are white (intentional ambiguity demo)
        metformin_cues = [
            ("metformin-500", "package_color", "white"),
            ("metformin-500", "stripe_color",  "blue"),
            ("metformin-500", "tablet_shape",  "round"),
            ("metformin-500", "storage_location", "bedside drawer"),
        ]
        amlodipine_cues = [
            ("amlodipine-5", "package_color", "white"),
            ("amlodipine-5", "stripe_color",  "red"),
            ("amlodipine-5", "tablet_shape",  "round"),
            ("amlodipine-5", "storage_location", "bedside drawer"),
        ]
        for mid, key, val in metformin_cues + amlodipine_cues:
            conn.execute(
                """INSERT OR IGNORE INTO medication_cues
                   (medication_id, cue_key, cue_value) VALUES (?, ?, ?)""",
                (mid, key, val),
            )

        # Patient memory — nickname is HOW RAZIA KNOWS her medicine, not clinical truth
        conn.execute(
            """INSERT OR IGNORE INTO patient_memory
               (patient_id, memory_key, memory_value) VALUES (?, ?, ?)""",
            ("razia-bibi", "metformin-500_nickname", "raat wali goli"),
        )
        conn.execute(
            """INSERT OR IGNORE INTO patient_memory
               (patient_id, memory_key, memory_value) VALUES (?, ?, ?)""",
            ("razia-bibi", "amlodipine-5_nickname", "BP wali goli"),
        )
        conn.execute(
            """INSERT OR IGNORE INTO patient_memory
               (patient_id, memory_key, memory_value) VALUES (?, ?, ?)""",
            ("razia-bibi", "preferred_address", "Ammi"),
        )


# ---------------------------------------------------------------------------
# Patient repository
# ---------------------------------------------------------------------------

def get_patient(patient_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
    return dict(row) if row else None


def get_all_patients() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM patients ORDER BY name").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Medication repository
# ---------------------------------------------------------------------------

def get_medications_for_patient(patient_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM medications WHERE patient_id = ? ORDER BY schedule_time",
            (patient_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_medication(medication_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM medications WHERE id = ?", (medication_id,)
        ).fetchone()
    return dict(row) if row else None


def get_medication_cues(medication_id: str) -> dict[str, str]:
    """Return all verified cues for a medication as {cue_key: cue_value}."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT cue_key, cue_value FROM medication_cues WHERE medication_id = ?",
            (medication_id,),
        ).fetchall()
    return {r["cue_key"]: r["cue_value"] for r in rows}


def get_all_medication_cues_for_patient(patient_id: str) -> dict[str, dict[str, str]]:
    """Return {medication_id: {cue_key: cue_value}} for all patient medications."""
    medications = get_medications_for_patient(patient_id)
    return {m["id"]: get_medication_cues(m["id"]) for m in medications}


# ---------------------------------------------------------------------------
# Patient memory repository
# ---------------------------------------------------------------------------

def get_patient_memory(patient_id: str) -> dict[str, str]:
    """Return all memory entries for a patient as {memory_key: memory_value}."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT memory_key, memory_value FROM patient_memory WHERE patient_id = ?",
            (patient_id,),
        ).fetchall()
    return {r["memory_key"]: r["memory_value"] for r in rows}


# ---------------------------------------------------------------------------
# Dose event repository
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_dose_event(
    patient_id: str,
    medication_id: str,
    scheduled_time: str,
    call_id: str | None = None,
    call_status: str = "scheduled",
) -> dict[str, Any]:
    """Create and return a new dose event."""
    event_id = str(uuid.uuid4())
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dose_events
               (id, patient_id, medication_id, scheduled_time, call_id,
                call_status, adherence_outcome, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
            (event_id, patient_id, medication_id, scheduled_time,
             call_id, call_status, now, now),
        )
    return {
        "id": event_id,
        "patientId": patient_id,
        "medicationId": medication_id,
        "scheduledTime": scheduled_time,
        "callId": call_id,
        "callStatus": call_status,
        "adherenceOutcome": None,
        "createdAt": now,
        "updatedAt": now,
    }


def update_dose_event(
    event_id: str,
    call_id: str | None = None,
    call_status: str | None = None,
    adherence_outcome: str | None = None,
) -> None:
    """Update mutable fields on a dose event."""
    sets: list[str] = ["updated_at = ?"]
    params: list[Any] = [_now_iso()]
    if call_id is not None:
        sets.append("call_id = ?")
        params.append(call_id)
    if call_status is not None:
        sets.append("call_status = ?")
        params.append(call_status)
    if adherence_outcome is not None:
        sets.append("adherence_outcome = ?")
        params.append(adherence_outcome)
    params.append(event_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE dose_events SET {', '.join(sets)} WHERE id = ?", params
        )


def get_recent_dose_events(patient_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    with _connect() as conn:
        if patient_id:
            rows = conn.execute(
                """SELECT * FROM dose_events WHERE patient_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (patient_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dose_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [
        {
            "id": r["id"],
            "patientId": r["patient_id"],
            "medicationId": r["medication_id"],
            "scheduledTime": r["scheduled_time"],
            "callId": r["call_id"],
            "callStatus": r["call_status"],
            "adherenceOutcome": r["adherence_outcome"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Escalation repository
# ---------------------------------------------------------------------------

def create_escalation(
    patient_id: str,
    reason: str,
    detail: str | None = None,
    dose_event_id: str | None = None,
) -> dict[str, Any]:
    """Create and return a new escalation record."""
    esc_id = str(uuid.uuid4())
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO escalations
               (id, patient_id, dose_event_id, reason, detail, created_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL)""",
            (esc_id, patient_id, dose_event_id, reason, detail, now),
        )
    return {
        "id": esc_id,
        "patientId": patient_id,
        "doseEventId": dose_event_id,
        "reason": reason,
        "detail": detail,
        "createdAt": now,
        "resolvedAt": None,
    }


# ---------------------------------------------------------------------------
# P2 dose event helpers
# ---------------------------------------------------------------------------

def _row_to_dose_event(r: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row from dose_events to a typed dict."""
    keys = r.keys()
    return {
        "id":               r["id"],
        "patientId":        r["patient_id"],
        "medicationId":     r["medication_id"],
        "scheduledTime":    r["scheduled_time"],
        "callId":           r["call_id"],
        "callStatus":       r["call_status"],
        "adherenceOutcome": r["adherence_outcome"],
        "scheduleKey":      r["schedule_key"] if "schedule_key" in keys else None,
        "retryCount":       r["retry_count"] if "retry_count" in keys else 0,
        "createdAt":        r["created_at"],
        "updatedAt":        r["updated_at"],
    }


def get_dose_event(event_id: str) -> dict[str, Any] | None:
    """Return a single dose event by ID, or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM dose_events WHERE id = ?", (event_id,)
        ).fetchone()
    return _row_to_dose_event(row) if row else None


def get_or_create_scheduled_dose_event(
    schedule_key: str,
    patient_id: str,
    medication_id: str,
    scheduled_time: str,
) -> tuple[dict[str, Any], bool]:
    """
    Idempotent: return (event, True) if inserted, (event, False) if already exists.
    The schedule_key uniquely identifies one scheduled dose occurrence
    (e.g. "razia-bibi:metformin-500:2026-08-08:21:00").
    """
    now = _now_iso()
    event_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO dose_events
               (id, patient_id, medication_id, scheduled_time,
                call_id, call_status, adherence_outcome,
                schedule_key, retry_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, NULL, 'scheduled', NULL, ?, 0, ?, ?)""",
            (event_id, patient_id, medication_id, scheduled_time,
             schedule_key, now, now),
        )
        row = conn.execute(
            "SELECT * FROM dose_events WHERE schedule_key = ?", (schedule_key,)
        ).fetchone()
    event = _row_to_dose_event(row)
    created = event["id"] == event_id
    return event, created


def get_active_dose_events() -> list[dict[str, Any]]:
    """Return dose events with telephony-active call_status."""
    statuses = ("calling", "dispatched", "dialing", "ringing", "answered")
    placeholders = ",".join("?" * len(statuses))
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT * FROM dose_events
                WHERE call_status IN ({placeholders})
                ORDER BY created_at DESC""",
            statuses,
        ).fetchall()
    return [_row_to_dose_event(r) for r in rows]


def get_pending_dose_events() -> list[dict[str, Any]]:
    """Return dose events with status 'scheduled' or 'due', ordered oldest first."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM dose_events
               WHERE call_status IN ('scheduled', 'due')
               ORDER BY created_at ASC""",
        ).fetchall()
    return [_row_to_dose_event(r) for r in rows]


def increment_retry_count(event_id: str) -> int:
    """Increment retry_count by 1 and return the new value."""
    with _connect() as conn:
        conn.execute(
            "UPDATE dose_events SET retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
            (_now_iso(), event_id),
        )
        row = conn.execute(
            "SELECT retry_count FROM dose_events WHERE id = ?", (event_id,)
        ).fetchone()
    return row["retry_count"] if row else 0


def delete_demo_dose_events() -> int:
    """
    Delete all dose_events (for demo reset).
    Preserves: patients, medications, medication_cues, patient_memory.
    Returns: number of rows deleted.
    """
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM dose_events")
        deleted = cursor.rowcount
    return deleted
