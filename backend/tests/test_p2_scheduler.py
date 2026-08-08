"""
DAWA P2 Scheduler Tests — 24 new tests (+ full suite regression).

Coverage:
  1-3   timezone + dose-event identity
  4-5   due-detection timing
  6-7   single-call concurrency
  8-13  retry policy
  14-16 demo endpoint validation
  17-19 dispatch payload verification
  20    idempotency across ticks
  21    completed ≠ TAKEN
  22-24 demo reset

ALL Uplift HTTP calls are mocked — no real calls are placed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def seeded_db():
    """Init schema and seed demo data in the isolated test DB."""
    from app.services.dawa_store import init_dawa_db, seed_demo_data
    init_dawa_db()
    seed_demo_data()


@pytest.fixture(autouse=True)
def reset_scheduler_module():
    """Reset module-level scheduler state before each test."""
    import app.services.scheduler as sched
    original_lock = sched._dispatch_lock
    original_sched = sched._scheduler
    sched._dispatch_lock = asyncio.Lock()
    sched._scheduler = None
    yield
    if sched._scheduler and sched._scheduler.running:
        sched._scheduler.shutdown(wait=False)
    sched._scheduler = original_sched
    sched._dispatch_lock = original_lock


def _make_p2_client(monkeypatch, *, assistant_id="asst-p2-test", phone="+923001234567"):
    """Create a P2 TestClient with controlled env vars and reloaded modules."""
    monkeypatch.setenv("UPLIFTAI_API_KEY", "test-api-key-p2")
    if assistant_id:
        monkeypatch.setenv("UPLIFT_ASSISTANT_ID", assistant_id)
    else:
        monkeypatch.delenv("UPLIFT_ASSISTANT_ID", raising=False)
    if phone:
        monkeypatch.setenv("TEST_PHONE_NUMBER", phone)
    else:
        monkeypatch.delenv("TEST_PHONE_NUMBER", raising=False)

    import importlib
    import app.config as cfg_mod
    import app.services.uplift as svc_mod
    import app.services.dawa_store as store_mod
    import app.services.call_context as ctx_mod
    import app.services.scheduler as sched_mod
    import app.api.test_call as api_mod
    import app.api.dawa as dawa_mod
    import app.main as main_mod

    importlib.reload(cfg_mod)
    importlib.reload(svc_mod)
    importlib.reload(ctx_mod)
    importlib.reload(sched_mod)
    importlib.reload(api_mod)
    importlib.reload(dawa_mod)
    importlib.reload(main_mod)

    from app.services.dawa_store import init_dawa_db, seed_demo_data
    init_dawa_db()
    seed_demo_data()

    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


def _mock_uplift_dispatch():
    """Mock httpx.AsyncClient for a successful Uplift /calls POST."""
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.post = AsyncMock(
        return_value=MagicMock(
            is_success=True,
            json=MagicMock(return_value={"callId": "mock-call-id"}),
        )
    )
    mock.get = AsyncMock(
        return_value=MagicMock(
            is_success=True,
            json=MagicMock(return_value={"sessions": []}),
        )
    )
    return mock


# ─── 1–3  Timezone + Dose-event identity ──────────────────────────────────────

def test_karachi_timezone_is_explicit():
    """Scheduler must use Asia/Karachi, never rely on server OS timezone."""
    from app.services.scheduler import KARACHI_TZ
    assert str(KARACHI_TZ) == "Asia/Karachi"


def test_repeated_scan_creates_one_dose_event():
    """Scanning twice at the same due moment must create exactly one dose event."""
    from app.services import scheduler as sched, dawa_store
    karachi = ZoneInfo("Asia/Karachi")
    # Metformin is scheduled at 21:00 Karachi
    test_now = datetime(2026, 8, 8, 21, 0, 30, tzinfo=karachi)

    async def run():
        with patch("app.services.scheduler.dispatch_call_via_uplift", new_callable=AsyncMock):
            await sched._scan_due_medications(now_override=test_now)
            await sched._scan_due_medications(now_override=test_now)

    asyncio.get_event_loop().run_until_complete(run())

    events = dawa_store.get_recent_dose_events(patient_id="razia-bibi")
    met_events = [e for e in events if e["medicationId"] == "metformin-500"]
    assert len(met_events) == 1, (
        f"Expected exactly 1 Metformin dose event, got {len(met_events)}"
    )


def test_idempotency_key_uses_event_id_and_attempt():
    """Idempotency key must be deterministic: '{event_id}:attempt:{retry_count}'."""
    from app.services import dawa_store
    event = dawa_store.create_dose_event("razia-bibi", "metformin-500", "21:00")
    expected_key = f"{event['id']}:attempt:0"

    captured_headers: dict = {}

    async def run():
        async def mock_post(url, json=None, headers=None, **kwargs):
            captured_headers.update(headers or {})
            return MagicMock(is_success=True, json=MagicMock(return_value={"callId": "x"}))

        with patch("app.services.scheduler.settings") as ms, \
             patch("app.services.scheduler.httpx.AsyncClient") as MockClient:
            ms.uplift_assistant_id = "asst-test"
            ms.test_phone_number = "+921234567890"
            ms.upliftai_api_key = "key"
            mc = AsyncMock()
            mc.post = mock_post
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mc)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.scheduler import dispatch_call_via_uplift
            await dispatch_call_via_uplift(event, retry_count=0)

    asyncio.get_event_loop().run_until_complete(run())
    assert captured_headers.get("Idempotency-Key") == expected_key


# ─── 4–5  Due-detection timing ────────────────────────────────────────────────

def test_future_medication_not_dispatched_early():
    """A medication scheduled for 21:00 must not be dispatched at 20:55."""
    from app.services import scheduler as sched, dawa_store
    karachi = ZoneInfo("Asia/Karachi")
    test_now = datetime(2026, 8, 8, 20, 55, 0, tzinfo=karachi)

    dispatch_calls = []

    async def run():
        async def mock_dispatch(event, retry_count=0):
            dispatch_calls.append(event["id"])
            return "x"
        with patch("app.services.scheduler.dispatch_call_via_uplift", new=mock_dispatch):
            await sched._scan_due_medications(now_override=test_now)

    asyncio.get_event_loop().run_until_complete(run())
    assert dispatch_calls == [], "Must not dispatch a medication 5 min before scheduled time"


def test_due_medication_dispatched_at_schedule_time():
    """A medication scheduled at 21:00 must be dispatched when scan runs at 21:00."""
    from app.services import scheduler as sched, dawa_store
    karachi = ZoneInfo("Asia/Karachi")
    test_now = datetime(2026, 8, 8, 21, 0, 0, tzinfo=karachi)

    dispatch_calls = []

    async def run():
        async def mock_dispatch(event, retry_count=0):
            dispatch_calls.append(event["id"])
            return "x"
        with patch("app.services.scheduler.dispatch_call_via_uplift", new=mock_dispatch):
            with patch("app.services.scheduler._get_lock", return_value=asyncio.Lock()):
                await sched._scan_due_medications(now_override=test_now)

    asyncio.get_event_loop().run_until_complete(run())
    met_calls = [c for c in dispatch_calls]
    assert len(met_calls) >= 1, "Due medication must be dispatched at scheduled time"


# ─── 6–7  Single-call concurrency ─────────────────────────────────────────────

def test_one_active_call_prevents_second_simultaneous_dispatch():
    """_safe_dispatch must not fire when the dispatch lock is already held."""
    from app.services import scheduler as sched, dawa_store

    event = dawa_store.create_dose_event("razia-bibi", "metformin-500", "21:00", call_status="due")

    dispatch_calls = []

    async def run():
        lock = sched._get_lock()
        # Simulate an active call by holding the lock
        await lock.acquire()

        async def mock_dispatch(e, retry_count=0):
            dispatch_calls.append(e["id"])
            return "x"

        with patch("app.services.scheduler.dispatch_call_via_uplift", new=mock_dispatch):
            await sched._safe_dispatch(event, 0)  # Should be blocked

        lock.release()

    asyncio.get_event_loop().run_until_complete(run())
    assert dispatch_calls == [], "Must not dispatch while lock is held (active call in progress)"


def test_pending_call_dispatches_after_lock_released():
    """After the active call completes and lock is released, dispatch succeeds."""
    from app.services import scheduler as sched, dawa_store

    event = dawa_store.create_dose_event("razia-bibi", "metformin-500", "21:00", call_status="due")
    dispatch_calls = []

    async def run():
        lock = sched._get_lock()

        # Simulate lock being free (no active call)
        async def mock_dispatch(e, retry_count=0):
            dispatch_calls.append(e["id"])
            return "call-id"

        with patch("app.services.scheduler.dispatch_call_via_uplift", new=mock_dispatch):
            # Lock is free — dispatch should proceed
            await sched._safe_dispatch(event, 0)

    asyncio.get_event_loop().run_until_complete(run())
    assert dispatch_calls == [event["id"]], "Dispatch must proceed when lock is free"


# ─── 8–13  Retry policy ──────────────────────────────────────────────────────

def test_busy_is_retryable():
    from app.services.scheduler import RETRYABLE_REASONS
    assert "busy" in RETRYABLE_REASONS


def test_no_answer_is_retryable():
    from app.services.scheduler import RETRYABLE_REASONS
    assert "no_answer" in RETRYABLE_REASONS


def test_network_error_is_retryable():
    from app.services.scheduler import RETRYABLE_REASONS
    assert "network_error" in RETRYABLE_REASONS


def test_declined_is_not_automatically_retried():
    from app.services.scheduler import NON_RETRYABLE_REASONS
    assert "declined" in NON_RETRYABLE_REASONS


def test_wrong_number_is_not_automatically_retried():
    from app.services.scheduler import NON_RETRYABLE_REASONS
    assert "wrong_number" in NON_RETRYABLE_REASONS


def test_retry_maximum_is_enforced():
    """MAX_RETRIES must be set and respected (no infinite retry loop)."""
    from app.services.scheduler import MAX_RETRIES
    assert MAX_RETRIES >= 1
    assert MAX_RETRIES <= 3, "Demo should use ≤ 3 retries; infinite loops are forbidden"


# ─── 14–16  Demo endpoint validation ─────────────────────────────────────────

def test_demo_delay_less_than_15_seconds_is_rejected(monkeypatch):
    """POST /api/dawa/schedule-demo-call with delaySeconds=10 must return 422."""
    client = _make_p2_client(monkeypatch)
    resp = client.post(
        "/api/dawa/schedule-demo-call",
        json={"patientId": "razia-bibi", "medicationId": "metformin-500", "delaySeconds": 10},
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"


def test_demo_delay_greater_than_300_seconds_is_rejected(monkeypatch):
    """POST /api/dawa/schedule-demo-call with delaySeconds=400 must return 422."""
    client = _make_p2_client(monkeypatch)
    resp = client.post(
        "/api/dawa/schedule-demo-call",
        json={"patientId": "razia-bibi", "medicationId": "metformin-500", "delaySeconds": 400},
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"


def test_demo_endpoint_cannot_accept_destination_phone(monkeypatch):
    """
    The schedule-demo-call body schema must not expose a 'phone' field.
    Verifies the Pydantic model rejects extra fields or ignores phone.
    """
    from app.api.dawa import ScheduleDemoCallRequest
    import pydantic

    # Model should not have a 'phone' field
    field_names = set(ScheduleDemoCallRequest.model_fields.keys())
    assert "phone" not in field_names, (
        "ScheduleDemoCallRequest must NOT expose a phone field"
    )
    assert "to" not in field_names, (
        "ScheduleDemoCallRequest must NOT expose a 'to' field"
    )


# ─── 17–19  Dispatch payload verification ─────────────────────────────────────

def test_dispatch_uses_test_phone_number():
    """dispatch_call_via_uplift must use TEST_PHONE_NUMBER from settings, not any arg."""
    from app.services import dawa_store
    event = dawa_store.create_dose_event("razia-bibi", "metformin-500", "21:00")
    captured: dict = {}

    async def run():
        async def mock_post(url, json=None, headers=None, **kwargs):
            captured.update(json or {})
            return MagicMock(is_success=True, json=MagicMock(return_value={"callId": "x"}))

        with patch("app.services.scheduler.settings") as ms, \
             patch("app.services.scheduler.httpx.AsyncClient") as MC:
            ms.uplift_assistant_id = "asst-test"
            ms.test_phone_number = "+923001234567"
            ms.upliftai_api_key = "key"
            mc = AsyncMock()
            mc.post = mock_post
            MC.return_value.__aenter__ = AsyncMock(return_value=mc)
            MC.return_value.__aexit__ = AsyncMock(return_value=False)
            from app.services.scheduler import dispatch_call_via_uplift
            await dispatch_call_via_uplift(event, 0)

    asyncio.get_event_loop().run_until_complete(run())
    assert captured.get("to") == "+923001234567"


def test_dispatch_uses_uplift_assistant_id():
    """dispatch_call_via_uplift must use UPLIFT_ASSISTANT_ID from settings."""
    from app.services import dawa_store
    event = dawa_store.create_dose_event("razia-bibi", "metformin-500", "21:00")
    captured: dict = {}

    async def run():
        async def mock_post(url, json=None, **kwargs):
            captured.update(json or {})
            return MagicMock(is_success=True, json=MagicMock(return_value={"callId": "x"}))

        with patch("app.services.scheduler.settings") as ms, \
             patch("app.services.scheduler.httpx.AsyncClient") as MC:
            ms.uplift_assistant_id = "asst-specific-id-xyz"
            ms.test_phone_number = "+921234567890"
            ms.upliftai_api_key = "key"
            mc = AsyncMock()
            mc.post = mock_post
            MC.return_value.__aenter__ = AsyncMock(return_value=mc)
            MC.return_value.__aexit__ = AsyncMock(return_value=False)
            from app.services.scheduler import dispatch_call_via_uplift
            await dispatch_call_via_uplift(event, 0)

    asyncio.get_event_loop().run_until_complete(run())
    assert captured.get("assistantId") == "asst-specific-id-xyz"


def test_dispatch_uses_verified_call_context():
    """dispatch_call_via_uplift must include 'variables' built from the DB."""
    from app.services import dawa_store
    event = dawa_store.create_dose_event("razia-bibi", "metformin-500", "21:00")
    captured: dict = {}

    async def run():
        async def mock_post(url, json=None, **kwargs):
            captured.update(json or {})
            return MagicMock(is_success=True, json=MagicMock(return_value={"callId": "x"}))

        with patch("app.services.scheduler.settings") as ms, \
             patch("app.services.scheduler.httpx.AsyncClient") as MC:
            ms.uplift_assistant_id = "asst-test"
            ms.test_phone_number = "+921234567890"
            ms.upliftai_api_key = "key"
            mc = AsyncMock()
            mc.post = mock_post
            MC.return_value.__aenter__ = AsyncMock(return_value=mc)
            MC.return_value.__aexit__ = AsyncMock(return_value=False)
            from app.services.scheduler import dispatch_call_via_uplift
            await dispatch_call_via_uplift(event, 0)

    asyncio.get_event_loop().run_until_complete(run())
    variables = captured.get("variables", {})
    assert "clinical_name" in variables, "variables must include clinical_name from DB"
    assert "nickname" in variables,      "variables must include nickname from DB"
    assert variables.get("clinical_name") == "Metformin"
    assert variables.get("nickname") == "raat wali goli"


# ─── 20  Idempotency across ticks ────────────────────────────────────────────

def test_repeated_ticks_do_not_duplicate_dispatches():
    """Two scheduler ticks at the same due time must dispatch exactly once."""
    from app.services import scheduler as sched, dawa_store
    karachi = ZoneInfo("Asia/Karachi")
    test_now = datetime(2026, 8, 8, 21, 1, 0, tzinfo=karachi)

    dispatched_ids: list[str] = []

    async def run():
        async def mock_dispatch(event, retry_count=0):
            dispatched_ids.append(event["id"])
            # Simulate call completing (so active check passes on second tick)
            dawa_store.update_dose_event(event["id"], call_status="completed")
            return "x"

        with patch("app.services.scheduler.dispatch_call_via_uplift", new=mock_dispatch):
            await sched._scan_due_medications(now_override=test_now)
            # Second tick — same time window
            await sched._scan_due_medications(now_override=test_now)

    asyncio.get_event_loop().run_until_complete(run())

    # Only one unique event ID should have been dispatched
    assert len(set(dispatched_ids)) == 1, (
        f"Expected 1 unique dispatch, got {len(set(dispatched_ids))}: {dispatched_ids}"
    )


# ─── 21  completed ≠ TAKEN ──────────────────────────────────────────────────

def test_completed_telephony_does_not_set_adherence_taken():
    """
    Updating call_status to 'completed' must never auto-set adherence_outcome.
    Telephony and adherence are explicitly separate.
    """
    from app.services.dawa_store import create_dose_event, update_dose_event, get_dose_event

    event = create_dose_event(
        "razia-bibi", "metformin-500", "21:00",
        call_id="completed-call-id", call_status="answered",
    )
    update_dose_event(event["id"], call_status="completed")

    updated = get_dose_event(event["id"])
    assert updated["callStatus"] == "completed"
    assert updated["adherenceOutcome"] is None, (
        f"adherenceOutcome must remain None after completed. Got: {updated['adherenceOutcome']!r}"
    )


# ─── 22–24  Demo reset ────────────────────────────────────────────────────────

def test_reset_preserves_razia_bibi():
    """POST /api/dawa/demo/reset must not delete the Razia Bibi patient record."""
    from app.services.dawa_store import delete_demo_dose_events, get_patient
    delete_demo_dose_events()
    assert get_patient("razia-bibi") is not None, "razia-bibi must survive demo reset"


def test_reset_preserves_medications():
    """POST /api/dawa/demo/reset must not delete any medications."""
    from app.services.dawa_store import delete_demo_dose_events, get_medications_for_patient
    delete_demo_dose_events()
    meds = get_medications_for_patient("razia-bibi")
    assert len(meds) == 2, f"Both medications must survive demo reset, got {len(meds)}"


def test_reset_removes_all_dose_events():
    """POST /api/dawa/demo/reset must remove all demo dose events."""
    from app.services.dawa_store import (
        create_dose_event, delete_demo_dose_events,
        get_recent_dose_events,
    )
    # Create a couple of demo events
    create_dose_event("razia-bibi", "metformin-500", "21:00", call_status="completed")
    create_dose_event("razia-bibi", "amlodipine-5", "08:00", call_status="failed")

    deleted = delete_demo_dose_events()
    assert deleted == 2, f"Expected 2 deleted, got {deleted}"

    remaining = get_recent_dose_events(patient_id="razia-bibi")
    assert remaining == [], f"No dose events should remain after reset, got {remaining}"
