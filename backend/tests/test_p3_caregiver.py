"""
DAWA P3 — Caregiver setup + verified doctor instructions (31 tests).

Coverage:
   1-5   idempotent migration preserves existing data
   6-11  medication CRUD via the caregiver API
  12-15  recognition cues
  16-19  auto_call_enabled / active gating of the scheduler
  20-24  backend-authoritative next-call computation (Asia/Karachi)
  25-28  deterministic doctor-instruction conflict warnings
  29-31  safety invariants (phone privacy, completed != TAKEN, single dispatch path)

ALL Uplift HTTP calls are mocked — no real calls are placed.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import seed_test_patient
from fastapi.testclient import TestClient

KARACHI = ZoneInfo("Asia/Karachi")


@pytest.fixture(autouse=True)
def seeded_db():
    from app.services.dawa_store import init_dawa_db
    from tests.conftest import TEST_CAREGIVER_ID
    init_dawa_db()
    seed_test_patient()
@pytest.fixture(autouse=True)
def reset_scheduler_module():
    import app.services.scheduler as sched
    sched._dispatch_lock = asyncio.Lock()
    sched._scheduler = None
    sched.reset_voice_cache()
    yield
    sched.reset_voice_cache()


@pytest.fixture
def client():
    from app.main import app
    from tests.conftest import TEST_AUTH_HEADERS
    with TestClient(app) as c:
        c.headers.update(TEST_AUTH_HEADERS)
        yield c


def _mk_med(client, **overrides):
    payload = {
        "clinicalName": "Losartan",
        "dosage": "50 mg",
        "doseInstruction": "1 tablet",
        "scheduleTime": "07:30",
    }
    payload.update(overrides)
    return client.post("/api/dawa/medications", json=payload)


# ---------------------------------------------------------------------------
# 1-5  Idempotent migration
# ---------------------------------------------------------------------------

def test_01_migration_adds_all_p3_medication_columns():
    from app.services.dawa_store import _connect
    with _connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(medications)")}
    for expected in (
        "active", "auto_call_enabled", "doctor_instructions",
        "doctor_name", "verified_at", "created_at", "updated_at",
    ):
        assert expected in cols, f"missing column {expected}"


def test_02_migration_adds_patient_voice_columns():
    from app.services.dawa_store import _connect
    with _connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(patients)")}
    assert "preferred_voice_id" in cols
    assert "preferred_voice_name" in cols


def test_03_migration_is_idempotent_and_preserves_rows():
    """Re-running init must not wipe or duplicate existing medications."""
    from app.services import dawa_store
    before = dawa_store.get_medications_for_patient("razia-bibi")
    dawa_store.init_dawa_db()
    dawa_store.init_dawa_db()
    seed_test_patient()
    after = dawa_store.get_medications_for_patient("razia-bibi")
    assert len(after) == len(before)
    assert {m["id"] for m in after} == {m["id"] for m in before}


def test_04_migration_preserves_caregiver_edits():
    """A caregiver value must survive a subsequent startup migration."""
    from app.services import dawa_store
    dawa_store.update_medication("metformin-500", doctor_name="Dr. Ahmed")
    dawa_store.init_dawa_db()
    seed_test_patient()
    assert dawa_store.get_medication("metformin-500")["doctor_name"] == "Dr. Ahmed"


def test_05_existing_medications_default_to_active_and_auto_calling():
    from app.services import dawa_store
    for med in dawa_store.get_medications_for_patient("razia-bibi"):
        assert med["active"] == 1
        assert med["auto_call_enabled"] == 1


# ---------------------------------------------------------------------------
# 6-11  Medication CRUD
# ---------------------------------------------------------------------------

def test_06_list_medications_returns_seeded_medications(client):
    body = client.get("/api/dawa/medications").json()
    ids = {m["id"] for m in body["medications"]}
    assert {"metformin-500", "amlodipine-5"} <= ids


def test_07_create_medication_persists(client):
    r = _mk_med(client)
    assert r.status_code == 201
    med = r.json()
    assert med["clinicalName"] == "Losartan"
    assert client.get(f"/api/dawa/medications/{med['id']}").status_code == 200


def test_08_create_medication_rejects_invalid_schedule_time(client):
    assert _mk_med(client, scheduleTime="25:00").status_code == 422
    assert _mk_med(client, scheduleTime="7pm").status_code == 422


def test_09_update_medication_changes_only_supplied_fields(client):
    med_id = _mk_med(client).json()["id"]
    client.put(f"/api/dawa/medications/{med_id}", json={"dosage": "100 mg"})
    med = client.get(f"/api/dawa/medications/{med_id}").json()
    assert med["dosage"] == "100 mg"
    assert med["clinicalName"] == "Losartan"  # untouched


def test_10_update_missing_medication_returns_404(client):
    assert client.put("/api/dawa/medications/nope", json={"dosage": "1"}).status_code == 404
    assert client.get("/api/dawa/medications/nope").status_code == 404


def test_11_deactivating_medication_keeps_the_record(client):
    """Deactivate must not delete — call history references the row."""
    med_id = _mk_med(client).json()["id"]
    client.put(f"/api/dawa/medications/{med_id}", json={"active": False})
    assert client.get(f"/api/dawa/medications/{med_id}").json()["active"] is False


# ---------------------------------------------------------------------------
# 12-15  Recognition cues
# ---------------------------------------------------------------------------

def test_12_create_medication_with_cues(client):
    med = _mk_med(client, cues={"package_color": "yellow", "tablet_shape": "oval"}).json()
    assert med["cues"]["package_color"] == "yellow"
    assert med["cues"]["tablet_shape"] == "oval"


def test_13_unknown_cue_keys_are_rejected(client):
    assert _mk_med(client, cues={"smell": "minty"}).status_code == 422


def test_14_blank_cue_value_removes_the_cue(client):
    """An absent cue must stay absent — DAWA must not claim a blank identifier."""
    med_id = _mk_med(client, cues={"package_color": "yellow"}).json()["id"]
    client.put(f"/api/dawa/medications/{med_id}", json={"cues": {"package_color": ""}})
    assert "package_color" not in client.get(f"/api/dawa/medications/{med_id}").json()["cues"]


def test_15_updating_cues_does_not_clobber_other_cues(client):
    med_id = _mk_med(
        client, cues={"package_color": "yellow", "storage_location": "shelf"}
    ).json()["id"]
    client.put(f"/api/dawa/medications/{med_id}", json={"cues": {"package_color": "green"}})
    cues = client.get(f"/api/dawa/medications/{med_id}").json()["cues"]
    assert cues["package_color"] == "green"
    assert cues["storage_location"] == "shelf"


# ---------------------------------------------------------------------------
# 16-19  Scheduler honors active / auto_call_enabled
# ---------------------------------------------------------------------------

def test_16_auto_call_eligibility_rules():
    from app.services.scheduler import is_auto_call_eligible
    assert is_auto_call_eligible({"active": 1, "auto_call_enabled": 1})
    assert not is_auto_call_eligible({"active": 0, "auto_call_enabled": 1})
    assert not is_auto_call_eligible({"active": 1, "auto_call_enabled": 0})
    assert not is_auto_call_eligible({"active": 0, "auto_call_enabled": 0})


@pytest.mark.asyncio
async def test_17_scan_skips_medication_with_auto_call_disabled():
    from app.services import dawa_store, scheduler as sched
    dawa_store.update_medication("metformin-500", auto_call_enabled=False)
    dawa_store.update_medication("amlodipine-5", active=False)
    now = datetime(2026, 8, 8, 21, 0, tzinfo=KARACHI)  # metformin's slot
    with patch.object(sched, "_safe_dispatch", new=AsyncMock()) as disp:
        await sched._scan_due_medications(now_override=now)
    disp.assert_not_called()


@pytest.mark.asyncio
async def test_18_scan_still_dispatches_enabled_medication():
    from app.services import scheduler as sched
    now = datetime(2026, 8, 8, 21, 0, tzinfo=KARACHI)
    with patch.object(sched, "_safe_dispatch", new=AsyncMock()) as disp:
        await sched._scan_due_medications(now_override=now)
    assert disp.await_count == 1


def test_19_manual_call_ignores_auto_call_disabled(client):
    """Turning auto-calling off must not disable the caregiver's Call now."""
    from app.services import dawa_store
    dawa_store.update_medication("metformin-500", auto_call_enabled=False)
    with patch("app.services.scheduler.dispatch_call_via_uplift",
               new=AsyncMock(return_value="call-xyz")):
        r = client.post("/api/dawa/medications/metformin-500/call")
    assert r.status_code == 200
    assert r.json()["callId"] == "call-xyz"


# ---------------------------------------------------------------------------
# 20-24  Next-call computation
# ---------------------------------------------------------------------------

def test_20_next_call_picks_the_soonest_upcoming_slot():
    from app.services.scheduler import compute_next_call
    now = datetime(2026, 8, 8, 6, 0, tzinfo=KARACHI)  # before 08:00
    assert compute_next_call("razia-bibi", now)["medicationId"] == "amlodipine-5"


def test_21_next_call_rolls_over_to_tomorrow():
    from app.services.scheduler import compute_next_call
    now = datetime(2026, 8, 8, 22, 0, tzinfo=KARACHI)  # after both slots
    nxt = compute_next_call("razia-bibi", now)
    assert nxt["medicationId"] == "amlodipine-5"
    assert datetime.fromisoformat(nxt["scheduledFor"]).date() == datetime(2026, 8, 9).date()


def test_22_next_call_is_computed_in_karachi_not_utc():
    """A UTC-naive-looking instant must still resolve against Karachi local time."""
    from app.services.scheduler import compute_next_call
    now_utc = datetime(2026, 8, 8, 3, 0, tzinfo=ZoneInfo("UTC"))  # 08:00 Karachi
    nxt = compute_next_call("razia-bibi", now_utc)
    assert nxt["scheduledFor"].endswith("+05:00")
    assert nxt["medicationId"] == "metformin-500"  # 08:00 just passed


def test_23_next_call_excludes_ineligible_medications():
    from app.services import dawa_store
    from app.services.scheduler import compute_next_call
    dawa_store.update_medication("amlodipine-5", auto_call_enabled=False)
    now = datetime(2026, 8, 8, 6, 0, tzinfo=KARACHI)
    assert compute_next_call("razia-bibi", now)["medicationId"] == "metformin-500"


def test_24_next_call_returns_null_when_nothing_eligible(client):
    from app.services import dawa_store
    for mid in ("metformin-500", "amlodipine-5"):
        dawa_store.update_medication(mid, active=False)
    assert client.get("/api/dawa/next-call").json()["nextCall"] is None


# ---------------------------------------------------------------------------
# 25-28  Deterministic conflict warnings
# ---------------------------------------------------------------------------

def test_25_conflicting_tablet_count_is_flagged():
    from app.services.conflict import detect_dose_conflict
    w = detect_dose_conflict("1 tablet", "Take 2 tablets after dinner")
    assert w and "verify" in w.lower()


def test_26_agreeing_instructions_produce_no_warning():
    from app.services.conflict import detect_dose_conflict
    assert detect_dose_conflict("1 tablet", "Give one tablet at night") is None


def test_27_ambiguous_note_stays_silent():
    """Prefer silence over a false alarm."""
    from app.services.conflict import detect_dose_conflict
    assert detect_dose_conflict("1 tablet", "Take with food") is None
    assert detect_dose_conflict("1 tablet", "half a tablet if dizzy") is None
    assert detect_dose_conflict("", "2 tablets") is None


def test_28_conflict_warns_but_never_blocks_the_save(client):
    r = _mk_med(client, doseInstruction="1 tablet",
                doctorInstructions="Doctor said 2 tablets daily")
    assert r.status_code == 201
    med = r.json()
    assert med["warnings"], "conflict should be surfaced"
    # Data is saved verbatim — nothing auto-resolved
    assert med["doseInstruction"] == "1 tablet"
    assert med["doctorInstructions"] == "Doctor said 2 tablets daily"


# ---------------------------------------------------------------------------
# 29-31  Safety invariants
# ---------------------------------------------------------------------------

def test_29_patient_payload_never_exposes_the_full_phone_number(client):
    """
    The caregiver must be able to see WHICH number DAWA will dial, so they can
    spot a typo — but the dialable number itself must never leave the server.
    """
    import json as _json
    from tests.conftest import TEST_PATIENT_PHONE

    payload = client.get("/api/dawa/patient").json()
    raw = _json.dumps(payload)

    assert payload["maskedPhone"], "caregiver needs a masked hint of the number"
    assert "*" in payload["maskedPhone"]
    assert TEST_PATIENT_PHONE not in raw

    # An unrecognised field name must not smuggle a new number in.
    client.put("/api/dawa/patient", json={"phoneNumber": "+920000000000"})
    after = client.get("/api/dawa/patient").json()
    assert after["maskedPhone"] == payload["maskedPhone"]
    assert TEST_PATIENT_PHONE not in _json.dumps(after)


def test_30_completed_call_is_not_reported_as_taken(client):
    from app.services import dawa_store
    ev = dawa_store.create_dose_event(
        patient_id="razia-bibi", medication_id="metformin-500",
        scheduled_time=datetime.now(KARACHI).isoformat(), call_status="completed",
    )
    row = next(c for c in client.get("/api/dawa/calls").json()["calls"] if c["id"] == ev["id"])
    assert row["callStatus"] == "completed"
    assert row["adherenceOutcome"] is None
    assert row["adherenceLabel"] != "TAKEN"


def test_31_manual_call_uses_the_single_authoritative_dispatch_path(client):
    """Call-now must not open its own Uplift code path."""
    from app.services import scheduler as sched
    with patch.object(sched, "dispatch_call_via_uplift",
                      new=AsyncMock(return_value="call-1")) as disp:
        r = client.post("/api/dawa/medications/metformin-500/call")
    assert r.status_code == 200
    disp.assert_awaited_once()
