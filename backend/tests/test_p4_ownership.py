"""
DAWA P4 — Caregiver auth + data ownership (13 tests).

Coverage:
   1    Unauthenticated request rejected (401)
   2    Wrong internal secret rejected (401)
   3    No patient before claim (404)
   4    Claim unowned demo patient — 201
   5    Claim same patient twice — 200 already_owned (idempotent)
   6    Different caregiver conflicts — 409
   7    GET /patient returns data after claim
   8    Caregiver B cannot access caregiver A's patient
   9    GET /demo returns data after claim
  10    GET /medications returns owned medications
  11    POST /demo/reset preserves owner_user_id
  12    POST /demo-call with wrong patientId → 404
  13    Medication call scoped to owned patient

ALL Uplift HTTP calls are mocked — no real calls are placed.
Relies on `isolate_db` + `setup_auth_env` autouse fixtures in conftest.py.
"""

from __future__ import annotations

import pytest

from tests.conftest import seed_test_patient
from fastapi.testclient import TestClient

from tests.conftest import TEST_AUTH_HEADERS, TEST_CAREGIVER_ID

CAREGIVER_B_ID = "test-caregiver-2"
AUTH_B = {
    "X-DAWA-INTERNAL-SECRET": "test-internal-secret-p4",
    "X-DAWA-CAREGIVER-ID": CAREGIVER_B_ID,
}
NO_AUTH = {}
BAD_SECRET = {
    "X-DAWA-INTERNAL-SECRET": "WRONG",
    "X-DAWA-CAREGIVER-ID": TEST_CAREGIVER_ID,
}


@pytest.fixture(autouse=True)
def empty_db():
    """
    Init schema only — no patient exists yet.

    These tests are about how a patient comes into existence and who may see it,
    so each test creates exactly the accounts it needs.
    """
    from app.services.dawa_store import init_dawa_db
    init_dawa_db()


PATIENT_BODY = {
    "name": "Razia Bibi",
    "preferredAddress": "Ammi",
    "phone": "+923001234567",
    "language": "ur",
}


def _create_patient(client, headers=TEST_AUTH_HEADERS, **overrides):
    """POST /patient as the given caregiver."""
    body = {**PATIENT_BODY, **overrides}
    return client.post("/api/dawa/patient", json=body, headers=headers)


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 1  Unauthenticated request
# ---------------------------------------------------------------------------

def test_01_unauthenticated_is_rejected(client):
    """GET /patient without auth headers returns 401."""
    resp = client.get("/api/dawa/patient", headers=NO_AUTH)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2  Wrong internal secret
# ---------------------------------------------------------------------------

def test_02_wrong_secret_rejected(client):
    """Wrong X-DAWA-INTERNAL-SECRET returns 401."""
    resp = client.get("/api/dawa/patient", headers=BAD_SECRET)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3  No patient before claim
# ---------------------------------------------------------------------------

def test_03_no_patient_before_setup(client):
    """A brand-new account starts empty — no patient is handed to it."""
    resp = client.get("/api/dawa/patient", headers=TEST_AUTH_HEADERS)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4  Claim unowned patient → 201
# ---------------------------------------------------------------------------

def test_04_caregiver_creates_their_own_patient(client):
    """POST /patient creates the caregiver's own patient, unverified to start."""
    resp = _create_patient(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Razia Bibi"
    # Calling is locked until the number is proved.
    assert data["phoneVerified"] is False


# ---------------------------------------------------------------------------
# 5  Claim same patient twice → 200 already_owned
# ---------------------------------------------------------------------------

def test_05_second_patient_for_same_caregiver_is_rejected(client):
    """One patient per account — a second create returns 409, not a duplicate."""
    assert _create_patient(client).status_code == 201
    resp = _create_patient(client, name="Someone Else")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 6  Conflict — another caregiver already owns it
# ---------------------------------------------------------------------------

def test_06_second_caregiver_gets_their_own_patient(client):
    """
    The multi-user guarantee: caregiver A creating a patient must not lock
    caregiver B out. B gets a separate record, not a conflict.
    """
    a = _create_patient(client, headers=TEST_AUTH_HEADERS)
    b = _create_patient(client, headers=AUTH_B, name="Akbar Ali",
                        phone="+923008888888")
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


# ---------------------------------------------------------------------------
# 7  GET /patient returns data after claim
# ---------------------------------------------------------------------------

def test_07_patient_endpoint_returns_masked_phone_only(client):
    """
    GET /patient shows enough of the number to spot a typo, never the whole
    thing — a stolen session must not yield a readable phone book.
    """
    created = _create_patient(client).json()
    resp = client.get("/api/dawa/patient", headers=TEST_AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == created["id"]
    assert data["name"] == "Razia Bibi"
    assert "+923001234567" not in str(data)
    assert data["maskedPhone"] and "•" in data["maskedPhone"] or "*" in str(data["maskedPhone"])


# ---------------------------------------------------------------------------
# 8  Ownership isolation — caregiver B cannot see caregiver A's patient
# ---------------------------------------------------------------------------

def test_08_caregiver_b_cannot_see_caregiver_a_patient(client):
    """After A sets up their patient, caregiver B still sees nothing."""
    _create_patient(client, headers=TEST_AUTH_HEADERS)
    resp = client.get("/api/dawa/patient", headers=AUTH_B)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 9  GET /demo returns data after claim
# ---------------------------------------------------------------------------

def test_09_demo_endpoint_after_claim(client):
    """GET /demo returns patient + medications after claim."""
    seed_test_patient()
    resp = client.get("/api/dawa/demo", headers=TEST_AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "patient" in data
    assert "medications" in data


# ---------------------------------------------------------------------------
# 10  GET /medications returns owned medications
# ---------------------------------------------------------------------------

def test_10_medications_after_claim(client):
    """GET /medications returns the caregiver's patient's medications after claim."""
    seed_test_patient()
    resp = client.get("/api/dawa/medications", headers=TEST_AUTH_HEADERS)
    assert resp.status_code == 200
    meds = resp.json()["medications"]
    assert len(meds) == 2
    ids = {m["id"] for m in meds}
    assert ids == {"metformin-500", "amlodipine-5"}


# ---------------------------------------------------------------------------
# 11  POST /demo/reset preserves owner_user_id
# ---------------------------------------------------------------------------

def test_11_demo_reset_preserves_ownership(client):
    """POST /demo/reset removes dose events but keeps caregiver ownership."""
    from app.services.dawa_store import _connect  # noqa

    seed_test_patient()

    # Create a dose event so there's something to delete
    from app.services.dawa_store import create_dose_event
    from datetime import datetime, timezone
    create_dose_event(
        patient_id="razia-bibi",
        medication_id="metformin-500",
        scheduled_time=datetime.now(timezone.utc).isoformat(),
        call_status="scheduled",
    )

    resp = client.post("/api/dawa/demo/reset", headers=TEST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["doseEventsDeleted"] >= 1

    # Verify ownership is intact after reset
    with _connect() as conn:
        row = conn.execute(
            "SELECT owner_user_id FROM patients WHERE id = ?", ("razia-bibi",)
        ).fetchone()
    assert row["owner_user_id"] == TEST_CAREGIVER_ID


# ---------------------------------------------------------------------------
# 12  POST /demo-call with wrong patientId → 404
# ---------------------------------------------------------------------------

def test_12_demo_call_wrong_patient_id_rejected(client):
    """POST /demo-call with a patientId not owned by this caregiver returns 404."""
    seed_test_patient()
    resp = client.post(
        "/api/dawa/demo-call",
        json={"patientId": "someone-else", "medicationId": "metformin-500"},
        headers=TEST_AUTH_HEADERS,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 13  Caregiver B cannot call caregiver A's medication
# ---------------------------------------------------------------------------

def test_13_medication_call_scoped_to_owned_patient(client):
    """Caregiver B cannot call caregiver A's medication — returns 404."""
    seed_test_patient()
    resp = client.post(
        "/api/dawa/medications/metformin-500/call",
        headers=AUTH_B,  # caregiver B — no patient
    )
    assert resp.status_code == 404
