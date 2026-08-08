"""
DAWA P1 persistent store.

Tables (all in the same SQLite file as the P0-A calls table):
  patients         — one patient per caregiver account (owner_user_id)
  medications      — medications per patient
  medication_cues  — caregiver-verified visual recognition cues
  dose_events      — call dispatch record + telephony lifecycle
  escalations      — safety escalation records
  patient_memory   — patient nicknames / aliases (separate from clinical truth)

There is no seed data: every patient is created by a caregiver at runtime.
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
# Errors
# ---------------------------------------------------------------------------

class PatientAlreadyExists(Exception):
    """Raised when a caregiver who already has a patient tries to create another."""


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

            -- P5 — phone ownership proof.  One live challenge per patient;
            -- the code itself is never stored, only a salted hash.
            CREATE TABLE IF NOT EXISTS phone_verifications (
                patient_id   TEXT PRIMARY KEY REFERENCES patients(id),
                phone_e164   TEXT NOT NULL,
                code_hash    TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                attempts     INTEGER NOT NULL DEFAULT 0,
                sent_at      TEXT NOT NULL
            );
        """)

        # ── P2 schema migration — safe to run on every startup ──────────────
        # Add columns that didn't exist in P1.  SQLite raises OperationalError
        # if a column already exists; we catch and ignore it.
        # ── P3 schema migration — caregiver setup + verified doctor notes ───
        # Every ALTER is additive with a default, so existing rows and demo
        # data survive untouched.
        for _alter in [
            "ALTER TABLE dose_events ADD COLUMN schedule_key TEXT",
            "ALTER TABLE dose_events ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
            # P3 — medication lifecycle + caregiver-verified doctor context
            "ALTER TABLE medications ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE medications ADD COLUMN auto_call_enabled INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE medications ADD COLUMN doctor_instructions TEXT",
            "ALTER TABLE medications ADD COLUMN doctor_name TEXT",
            "ALTER TABLE medications ADD COLUMN verified_at TEXT",
            "ALTER TABLE medications ADD COLUMN created_at TEXT",
            "ALTER TABLE medications ADD COLUMN updated_at TEXT",
            # P3 — patient-level DAWA voice preference (UX only, never clinical)
            "ALTER TABLE patients ADD COLUMN preferred_voice_id TEXT",
            "ALTER TABLE patients ADD COLUMN preferred_voice_name TEXT",
            # P4 — caregiver data ownership; NULL means unclaimed
            "ALTER TABLE patients ADD COLUMN owner_user_id TEXT",
            # P5 — real multi-user: each patient carries the number DAWA dials.
            # phone_verified_at NULL means "never proved" — no call may go out.
            "ALTER TABLE patients ADD COLUMN phone_e164 TEXT",
            "ALTER TABLE patients ADD COLUMN phone_verified_at TEXT",
            # Per-patient Uplift assistant. Without this every patient shares one
            # assistant whose voice is PATCHed before each call, so two patients
            # dialling at once race and the loser hears the wrong voice.
            "ALTER TABLE patients ADD COLUMN assistant_id TEXT",
            "ALTER TABLE patients ADD COLUMN created_at TEXT",
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

        # One patient per caregiver account.  Enforced in the schema rather than
        # in application code so a duplicate POST /patient can never half-succeed.
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_patients_owner
               ON patients(owner_user_id)
               WHERE owner_user_id IS NOT NULL"""
        )

        # ── Backfill for rows created before a column existed ───────────────
        # COALESCE everywhere: a caregiver's saved value is never overwritten.
        now = _now_iso()
        conn.execute(
            "UPDATE medications SET created_at = COALESCE(created_at, ?), "
            "updated_at = COALESCE(updated_at, ?) WHERE created_at IS NULL",
            (now, now),
        )
        conn.execute(
            "UPDATE patients SET created_at = COALESCE(created_at, ?) "
            "WHERE created_at IS NULL",
            (now,),
        )
        from app.services.voice_catalog import DEFAULT_VOICE_ID, voice_name  # noqa: PLC0415
        conn.execute(
            "UPDATE patients SET preferred_voice_id = COALESCE(preferred_voice_id, ?), "
            "preferred_voice_name = COALESCE(preferred_voice_name, ?) "
            "WHERE preferred_voice_id IS NULL",
            (DEFAULT_VOICE_ID, voice_name(DEFAULT_VOICE_ID)),
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


def get_patient_by_owner(owner_user_id: str) -> dict[str, Any] | None:
    """Return the patient owned by this caregiver, or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE owner_user_id = ?", (owner_user_id,)
        ).fetchone()
    return dict(row) if row else None


def create_patient_for_owner(
    owner_user_id: str,
    name: str,
    preferred_address: str,
    phone_e164: str,
    language: str = "ur",
    literacy_mode: str = "voice_first",
) -> dict[str, Any]:
    """
    Create this caregiver's patient and return the stored row.

    The patient ID is generated, never fixed — every account gets its own
    record. Raises PatientAlreadyExists if the caregiver already has one;
    the unique index on owner_user_id is what actually enforces this, so a
    duplicate concurrent POST loses at the database rather than racing.

    The phone starts UNVERIFIED. Nothing dials it until it is proved.
    """
    from app.services.voice_catalog import DEFAULT_VOICE_ID, voice_name  # noqa: PLC0415

    patient_id = f"pt_{uuid.uuid4().hex[:16]}"
    now = _now_iso()
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO patients
                   (id, name, preferred_address, language, literacy_mode,
                    owner_user_id, phone_e164, phone_verified_at,
                    preferred_voice_id, preferred_voice_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)""",
                (
                    patient_id, name, preferred_address, language, literacy_mode,
                    owner_user_id, phone_e164,
                    DEFAULT_VOICE_ID, voice_name(DEFAULT_VOICE_ID), now,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise PatientAlreadyExists(
            f"Caregiver {owner_user_id!r} already has a patient."
        ) from exc

    created = get_patient(patient_id)
    assert created is not None  # just inserted inside a committed transaction
    return created


def update_patient_phone(patient_id: str, phone_e164: str) -> None:
    """
    Point the patient at a new number and drop any proof we had.

    Changing the number MUST clear phone_verified_at — otherwise a caregiver
    could verify their own phone, then swap in an arbitrary number and have
    DAWA cold-call a stranger on a schedule.
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE patients SET phone_e164 = ?, phone_verified_at = NULL WHERE id = ?",
            (phone_e164, patient_id),
        )
        conn.execute("DELETE FROM phone_verifications WHERE patient_id = ?", (patient_id,))


def mark_phone_verified(patient_id: str) -> None:
    """Record proof that this patient's number answers, and clear the challenge."""
    with _connect() as conn:
        conn.execute(
            "UPDATE patients SET phone_verified_at = ? WHERE id = ?",
            (_now_iso(), patient_id),
        )
        conn.execute("DELETE FROM phone_verifications WHERE patient_id = ?", (patient_id,))


def set_patient_assistant_id(patient_id: str, assistant_id: str | None) -> None:
    """Set or clear the patient's cached dedicated Uplift assistant ID."""
    with _connect() as conn:
        conn.execute(
            "UPDATE patients SET assistant_id = ? WHERE id = ?",
            (assistant_id, patient_id),
        )


def get_patients_with_verified_phone() -> list[dict[str, Any]]:
    """
    Every patient the scheduler is allowed to call.

    Unverified and unowned patients are excluded here rather than at dispatch
    time, so an unproved number cannot reach Uplift by any scheduler path.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM patients "
            "WHERE owner_user_id IS NOT NULL "
            "  AND phone_e164 IS NOT NULL "
            "  AND phone_verified_at IS NOT NULL "
            "ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Phone verification challenges
# ---------------------------------------------------------------------------

def upsert_phone_verification(
    patient_id: str,
    phone_e164: str,
    code_hash: str,
    expires_at: str,
) -> None:
    """Store (or replace) the live challenge for this patient."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO phone_verifications
               (patient_id, phone_e164, code_hash, expires_at, attempts, sent_at)
               VALUES (?, ?, ?, ?, 0, ?)
               ON CONFLICT(patient_id) DO UPDATE SET
                 phone_e164 = excluded.phone_e164,
                 code_hash  = excluded.code_hash,
                 expires_at = excluded.expires_at,
                 attempts   = 0,
                 sent_at    = excluded.sent_at""",
            (patient_id, phone_e164, code_hash, expires_at, _now_iso()),
        )


def get_phone_verification(patient_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM phone_verifications WHERE patient_id = ?", (patient_id,)
        ).fetchone()
    return dict(row) if row else None


def increment_phone_verification_attempts(patient_id: str) -> int:
    """Count a failed guess and return the new total."""
    with _connect() as conn:
        conn.execute(
            "UPDATE phone_verifications SET attempts = attempts + 1 WHERE patient_id = ?",
            (patient_id,),
        )
        row = conn.execute(
            "SELECT attempts FROM phone_verifications WHERE patient_id = ?", (patient_id,)
        ).fetchone()
    return int(row["attempts"]) if row else 0


def clear_phone_verification(patient_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM phone_verifications WHERE patient_id = ?", (patient_id,))


def delete_patient_dose_events(patient_id: str) -> int:
    """Delete all dose events for the given patient. Returns number of rows deleted."""
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM dose_events WHERE patient_id = ?", (patient_id,)
        )
        return cursor.rowcount


def get_all_patients() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM patients ORDER BY name").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Medication repository
# ---------------------------------------------------------------------------

def get_medications_for_patient(
    patient_id: str, include_inactive: bool = True
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM medications WHERE patient_id = ?"
    if not include_inactive:
        sql += " AND active = 1"
    sql += " ORDER BY schedule_time"
    with _connect() as conn:
        rows = conn.execute(sql, (patient_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# P3 — medication CRUD (caregiver is the verified human source of truth)
# ---------------------------------------------------------------------------

_MEDICATION_EDITABLE_FIELDS = (
    "clinical_name", "nickname", "dosage", "dose_instruction",
    "food_instruction", "schedule_time", "routine_anchor",
    "active", "auto_call_enabled", "doctor_instructions",
    "doctor_name", "verified_at",
)


def create_medication(patient_id: str, **fields: Any) -> dict[str, Any]:
    """
    Insert a caregiver-created medication.  Returns the stored row.

    Only whitelisted clinical fields are accepted — a caller cannot inject
    arbitrary columns.
    """
    now = _now_iso()
    med_id = fields.pop("id", None) or f"med-{uuid.uuid4().hex[:12]}"
    data: dict[str, Any] = {
        "id": med_id,
        "patient_id": patient_id,
        "clinical_name": fields.get("clinical_name", ""),
        "nickname": fields.get("nickname"),
        "dosage": fields.get("dosage", ""),
        "dose_instruction": fields.get("dose_instruction", ""),
        "food_instruction": fields.get("food_instruction") or "none",
        "schedule_time": fields.get("schedule_time", ""),
        "routine_anchor": fields.get("routine_anchor") or "",
        "active": 1 if fields.get("active", True) else 0,
        "auto_call_enabled": 1 if fields.get("auto_call_enabled", True) else 0,
        "doctor_instructions": fields.get("doctor_instructions"),
        "doctor_name": fields.get("doctor_name"),
        "verified_at": fields.get("verified_at") or now,
        "created_at": now,
        "updated_at": now,
    }
    cols = ", ".join(data)
    placeholders = ", ".join("?" for _ in data)
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO medications ({cols}) VALUES ({placeholders})",
            tuple(data.values()),
        )
    return get_medication(med_id)  # type: ignore[return-value]


def update_medication(medication_id: str, **fields: Any) -> dict[str, Any] | None:
    """
    Patch a medication.  Only whitelisted fields are written.

    Historical dose_events are deliberately NOT rewritten — changing a schedule
    affects future occurrences only.
    """
    updates: dict[str, Any] = {}
    for key in _MEDICATION_EDITABLE_FIELDS:
        if key in fields and fields[key] is not None:
            val = fields[key]
            if key in ("active", "auto_call_enabled"):
                val = 1 if val else 0
            updates[key] = val
    if not updates:
        return get_medication(medication_id)

    updates["updated_at"] = _now_iso()
    assignments = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        conn.execute(
            f"UPDATE medications SET {assignments} WHERE id = ?",
            (*updates.values(), medication_id),
        )
    return get_medication(medication_id)


def set_medication_cues(medication_id: str, cues: dict[str, str]) -> dict[str, str]:
    """
    Replace the verified recognition cues for a medication.

    Empty/blank values REMOVE a cue rather than storing a blank — an absent cue
    must stay absent so DAWA never claims it can visually identify the medicine.
    """
    with _connect() as conn:
        for key, value in cues.items():
            clean = (value or "").strip()
            if clean:
                conn.execute(
                    """INSERT INTO medication_cues (medication_id, cue_key, cue_value)
                       VALUES (?, ?, ?)
                       ON CONFLICT(medication_id, cue_key)
                       DO UPDATE SET cue_value = excluded.cue_value""",
                    (medication_id, key, clean),
                )
            else:
                conn.execute(
                    "DELETE FROM medication_cues WHERE medication_id = ? AND cue_key = ?",
                    (medication_id, key),
                )
    return get_medication_cues(medication_id)


# ---------------------------------------------------------------------------
# P3 — patient profile + DAWA voice preference
# ---------------------------------------------------------------------------

_PATIENT_EDITABLE_FIELDS = ("name", "preferred_address", "language", "literacy_mode")


def update_patient(patient_id: str, **fields: Any) -> dict[str, Any] | None:
    """
    Patch editable patient preferences.

    Phone number is intentionally NOT a column here — the calling destination
    always comes from the server-side TEST_PHONE_NUMBER secret.
    """
    updates = {
        k: fields[k]
        for k in _PATIENT_EDITABLE_FIELDS
        if k in fields and fields[k] is not None
    }
    if not updates:
        return get_patient(patient_id)
    assignments = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        conn.execute(
            f"UPDATE patients SET {assignments} WHERE id = ?",
            (*updates.values(), patient_id),
        )
    return get_patient(patient_id)


def set_patient_voice(
    patient_id: str, voice_id: str, voice_name: str | None = None
) -> dict[str, Any] | None:
    """
    Persist the patient's DAWA voice preference.

    Callers MUST only invoke this after Uplift has confirmed the assistant TTS
    update succeeded, so the DB can never claim a voice the assistant isn't using.
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE patients SET preferred_voice_id = ?, preferred_voice_name = ? WHERE id = ?",
            (voice_id, voice_name, patient_id),
        )
    return get_patient(patient_id)


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


def get_active_dose_events(patient_id: str | None = None) -> list[dict[str, Any]]:
    """
    Return dose events with telephony-active call_status.

    Pass patient_id to scope the check to one patient. The scheduler does this so
    that one patient's in-flight call does not block reminders for every other
    caregiver's patient — with multiple accounts, a global check would make the
    busiest patient starve everyone else.
    """
    statuses = ("calling", "dispatched", "dialing", "ringing", "answered")
    placeholders = ",".join("?" * len(statuses))
    sql = f"SELECT * FROM dose_events WHERE call_status IN ({placeholders})"
    params: list[Any] = list(statuses)
    if patient_id is not None:
        sql += " AND patient_id = ?"
        params.append(patient_id)
    sql += " ORDER BY created_at DESC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dose_event(r) for r in rows]


def get_pending_dose_events(patient_id: str | None = None) -> list[dict[str, Any]]:
    """Return dose events with status 'scheduled' or 'due', ordered oldest first."""
    sql = "SELECT * FROM dose_events WHERE call_status IN ('scheduled', 'due')"
    params: list[Any] = []
    if patient_id is not None:
        sql += " AND patient_id = ?"
        params.append(patient_id)
    sql += " ORDER BY created_at ASC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
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
