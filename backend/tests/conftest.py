"""
Shared pytest fixtures for the DAWA backend test suite.

Key fixtures:
  `isolate_db`     — redirects every test to a fresh temporary SQLite DB
  `setup_auth_env` — sets DAWA_INTERNAL_API_SECRET so P4 auth dependency works

Constants exported for test files:
  TEST_CAREGIVER_ID  — stable caregiver identity used in all test fixtures
  TEST_AUTH_HEADERS  — headers dict to include in every authenticated request
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# P4 test constants — used by every test file that hits authenticated routes
# ---------------------------------------------------------------------------

TEST_CAREGIVER_ID = "test-caregiver-1"

# These headers are injected by the TypeScript API gateway in production.
# In tests we simulate that gateway by setting them directly on the client.
TEST_AUTH_HEADERS = {
    "X-DAWA-INTERNAL-SECRET": "test-internal-secret-p4",
    "X-DAWA-CAREGIVER-ID": TEST_CAREGIVER_ID,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_db(monkeypatch, tmp_path):
    """
    Point DAWA_DB_PATH at a per-test temporary file before each test and
    unset it afterwards.  Because dawa_store._db_path() reads the env var at
    connection time, no module reload is required — the next connect() call
    automatically uses the fresh path.
    """
    db_file = tmp_path / "test_calls.db"
    monkeypatch.setenv("DAWA_DB_PATH", str(db_file))
    yield
    # monkeypatch restores the env var automatically after yield


@pytest.fixture(autouse=True)
def setup_auth_env(monkeypatch):
    """
    Set DAWA_INTERNAL_API_SECRET to a known test value before each test.
    Must match the TEST_AUTH_HEADERS secret so the FastAPI dependency
    get_current_caregiver_id passes for authenticated requests.
    """
    monkeypatch.setenv("DAWA_INTERNAL_API_SECRET", "test-internal-secret-p4")


# ---------------------------------------------------------------------------
# Test data factory
# ---------------------------------------------------------------------------
#
# Production seeds nothing — every patient is created by a caregiver at runtime.
# The suite still needs a known fixture, and in particular needs the two
# white-boxed medications that the whole ambiguity-resolution story is built on:
#
#   metformin-500  (raat wali goli) — white box, BLUE stripe
#   amlodipine-5   (BP wali goli)   — white box, RED stripe
#
# Fixed IDs are used deliberately so existing assertions keep their meaning.
# Rows are inserted directly rather than through create_patient_for_owner()
# because that function generates an ID by design.

DEMO_PATIENT_ID = "razia-bibi"
TEST_PATIENT_PHONE = "+923001234567"

# The fixture patient already has its own Uplift assistant, like any patient
# that has been called before. Without this the dispatch path would try to
# create one mid-test and hit the mocked HTTP client.
TEST_ASSISTANT_ID = "asst-test-razia"


def seed_test_patient(
    owner_user_id: str = TEST_CAREGIVER_ID,
    patient_id: str = DEMO_PATIENT_ID,
    *,
    phone: str | None = TEST_PATIENT_PHONE,
    verified: bool = True,
    with_medications: bool = True,
) -> str:
    """
    Insert an owned, phone-verified patient plus the standard medication fixture.

    Set verified=False to exercise the "cannot call an unproved number" paths.
    Returns the patient ID.
    """
    from datetime import datetime, timezone

    from app.services.dawa_store import _connect  # noqa: PLC0415
    from app.services.voice_catalog import DEFAULT_VOICE_ID, voice_name  # noqa: PLC0415

    now = datetime.now(timezone.utc).isoformat()
    verified_at = now if (verified and phone) else None

    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO patients
               (id, name, preferred_address, language, literacy_mode,
                owner_user_id, phone_e164, phone_verified_at, assistant_id,
                preferred_voice_id, preferred_voice_name, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                patient_id, "Razia Bibi", "Ammi", "ur", "voice_first",
                owner_user_id, phone, verified_at, TEST_ASSISTANT_ID,
                DEFAULT_VOICE_ID, voice_name(DEFAULT_VOICE_ID), now,
            ),
        )

        if not with_medications:
            return patient_id

        for med in (
            ("metformin-500", "Metformin", "500 mg", "1 tablet",
             "after dinner", "21:00", "after dinner", "raat wali goli"),
            ("amlodipine-5", "Amlodipine", "5 mg", "1 tablet",
             "none", "08:00", "morning", "BP wali goli"),
        ):
            conn.execute(
                """INSERT OR IGNORE INTO medications
                   (id, patient_id, clinical_name, dosage, dose_instruction,
                    food_instruction, schedule_time, routine_anchor, nickname,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (med[0], patient_id, *med[1:], now, now),
            )

        # BOTH packages are white — the intentional ambiguity the VMR resolves.
        cues = [
            ("metformin-500", "package_color", "white"),
            ("metformin-500", "stripe_color", "blue"),
            ("metformin-500", "tablet_shape", "round"),
            ("metformin-500", "storage_location", "bedside drawer"),
            ("amlodipine-5", "package_color", "white"),
            ("amlodipine-5", "stripe_color", "red"),
            ("amlodipine-5", "tablet_shape", "round"),
            ("amlodipine-5", "storage_location", "bedside drawer"),
        ]
        for mid, key, val in cues:
            conn.execute(
                """INSERT OR IGNORE INTO medication_cues
                   (medication_id, cue_key, cue_value) VALUES (?, ?, ?)""",
                (mid, key, val),
            )

        # Nicknames are how the patient knows her medicine, not clinical truth.
        for key, val in (
            ("metformin-500_nickname", "raat wali goli"),
            ("amlodipine-5_nickname", "BP wali goli"),
            ("preferred_address", "Ammi"),
        ):
            conn.execute(
                """INSERT OR IGNORE INTO patient_memory
                   (patient_id, memory_key, memory_value) VALUES (?, ?, ?)""",
                (patient_id, key, val),
            )

    return patient_id
