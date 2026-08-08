"""
DAWA P1 Conformance Tests — 18 tests.

Coverage:
  1-3   seed idempotency and demo data sanity
  4-9   VMR resolver (UNIQUE / AMBIGUOUS / NO_MATCH)
  10-11 call context (verified cues, nickname vs. clinical name)
  12-15 size limits and idempotency key on demo-call
  16-17 P0-A routes preserved
  18    completed call ≠ adherence TAKEN

ALL Uplift HTTP calls are mocked — no real calls are placed.
Relies on `isolate_db` autouse fixture in conftest.py to give each test
a fresh SQLite file.  Schema initialisation and seeding are done explicitly
here so they work whether or not the FastAPI lifespan fires.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import seed_test_patient
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def seeded_db():
    """
    Initialise the P1 schema and seed demo data in the isolated test DB.
    This fixture runs for every test; safe because of the isolate_db autouse
    fixture in conftest.py (each test gets a fresh tmp SQLite file).
    """
    from app.services.dawa_store import init_dawa_db
    from tests.conftest import TEST_CAREGIVER_ID
    init_dawa_db()
    seed_test_patient()
def _make_p1_client(
    monkeypatch,
    *,
    assistant_id: str | None = "asst-p1-test-123",
    phone: str | None = "+923001234567",
) -> TestClient:
    """Create a P1 TestClient with controlled env vars, reloading Settings."""
    monkeypatch.setenv("UPLIFTAI_API_KEY", "test-api-key-p1")
    monkeypatch.setenv("DAWA_INTERNAL_API_SECRET", "test-internal-secret-p4")
    if assistant_id is not None:
        monkeypatch.setenv("UPLIFT_ASSISTANT_ID", assistant_id)
    else:
        monkeypatch.delenv("UPLIFT_ASSISTANT_ID", raising=False)
    if phone is not None:
        monkeypatch.setenv("TEST_PHONE_NUMBER", phone)
    else:
        monkeypatch.delenv("TEST_PHONE_NUMBER", raising=False)
    monkeypatch.delenv("DAWA_ADMIN_TOKEN", raising=False)

    import importlib
    import app.config as cfg_mod
    import app.services.uplift as svc_mod
    import app.services.call_context as ctx_mod
    import app.services.scheduler as sched_mod
    import app.api.test_call as api_mod
    import app.api.dawa as dawa_api_mod
    import app.main as main_mod

    importlib.reload(cfg_mod)
    importlib.reload(svc_mod)
    importlib.reload(ctx_mod)
    importlib.reload(sched_mod)
    importlib.reload(api_mod)
    importlib.reload(dawa_api_mod)
    importlib.reload(main_mod)

    from app.main import app  # noqa: PLC0415
    from app.services.dawa_store import init_dawa_db  # noqa: PLC0415
    from tests.conftest import TEST_CAREGIVER_ID, TEST_AUTH_HEADERS  # noqa: PLC0415
    init_dawa_db()
    seed_test_patient()
    c = TestClient(app)
    c.headers.update(TEST_AUTH_HEADERS)
    return c


def _mock_uplift_call(call_id: str = "call-p1-test") -> MagicMock:
    """Return a mock httpx.AsyncClient that fakes a successful Uplift /calls POST."""
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    response = MagicMock()
    response.is_success = True
    response.json.return_value = {"callId": call_id}
    mock.post = AsyncMock(return_value=response)
    mock.get = AsyncMock(return_value=MagicMock(is_success=True, json=lambda: {"sessions": []}))
    return mock


# ---------------------------------------------------------------------------
# 1–3  Seed & demo data
# ---------------------------------------------------------------------------

def test_a_caregiver_can_only_ever_have_one_patient():
    """
    The one-patient-per-account rule is enforced by the database, not by a
    check in the route — so a duplicate create cannot slip through a race.
    """
    from app.services.dawa_store import (
        PatientAlreadyExists,
        create_patient_for_owner,
        get_all_patients,
    )
    from tests.conftest import TEST_CAREGIVER_ID

    with pytest.raises(PatientAlreadyExists):
        create_patient_for_owner(
            owner_user_id=TEST_CAREGIVER_ID,
            name="Second Patient",
            preferred_address="Abbu",
            phone_e164="+923009999999",
        )

    owned = [p for p in get_all_patients() if p["owner_user_id"] == TEST_CAREGIVER_ID]
    assert len(owned) == 1, f"Expected exactly 1 owned patient, got {len(owned)}"


def test_two_caregivers_get_separate_patients():
    """
    The core multi-user guarantee: a second caregiver creates their own record
    rather than colliding with, or being locked out by, the first.
    """
    from app.services.dawa_store import create_patient_for_owner, get_patient_by_owner

    created = create_patient_for_owner(
        owner_user_id="test-caregiver-2",
        name="Akbar Ali",
        preferred_address="Abbu",
        phone_e164="+923008888888",
    )

    assert created["id"] != "razia-bibi"
    assert created["owner_user_id"] == "test-caregiver-2"
    # A brand-new patient is never callable until the number is proved.
    assert created["phone_verified_at"] is None

    mine = get_patient_by_owner("test-caregiver-2")
    theirs = get_patient_by_owner("test-caregiver-1")
    assert mine is not None and theirs is not None
    assert mine["id"] != theirs["id"]


def test_demo_data_has_two_medications():
    """Razia Bibi has exactly two medications after seeding."""
    from app.services.dawa_store import get_medications_for_patient
    meds = get_medications_for_patient("razia-bibi")
    assert len(meds) == 2
    ids = {m["id"] for m in meds}
    assert ids == {"metformin-500", "amlodipine-5"}


def test_both_medications_have_white_package():
    """Both medications must be white — this is the intentional ambiguity demo."""
    from app.services.dawa_store import get_medication_cues
    metformin_cues = get_medication_cues("metformin-500")
    amlodipine_cues = get_medication_cues("amlodipine-5")
    assert metformin_cues.get("package_color") == "white"
    assert amlodipine_cues.get("package_color") == "white"


# ---------------------------------------------------------------------------
# 4–9  VMR resolver
# ---------------------------------------------------------------------------

def test_white_only_is_ambiguous():
    """{package_color: white} alone must return AMBIGUOUS (both packages are white)."""
    from app.services.vmr import resolve
    result = resolve("razia-bibi", {"package_color": "white"})
    assert result.status == "AMBIGUOUS"
    assert set(result.candidate_medication_ids) == {"metformin-500", "amlodipine-5"}


def test_ambiguous_best_discriminator_is_stripe_color():
    """When both meds are white, the best discriminator must be stripe_color."""
    from app.services.vmr import resolve
    result = resolve("razia-bibi", {"package_color": "white"})
    assert result.best_discriminator == "stripe_color"


def test_white_blue_resolves_to_metformin():
    """{package_color: white, stripe_color: blue} must resolve UNIQUE → metformin-500."""
    from app.services.vmr import resolve
    result = resolve("razia-bibi", {"package_color": "white", "stripe_color": "blue"})
    assert result.status == "UNIQUE"
    assert result.medication_id == "metformin-500"


def test_white_red_resolves_to_amlodipine():
    """{package_color: white, stripe_color: red} must resolve UNIQUE → amlodipine-5."""
    from app.services.vmr import resolve
    result = resolve("razia-bibi", {"package_color": "white", "stripe_color": "red"})
    assert result.status == "UNIQUE"
    assert result.medication_id == "amlodipine-5"


def test_unknown_cue_is_no_match():
    """A cue key not present in any medication's verified cues must return NO_MATCH."""
    from app.services.vmr import resolve
    result = resolve("razia-bibi", {"completely_unknown_property": "anything"})
    assert result.status == "NO_MATCH"


def test_vmr_result_has_no_confidence_or_probability_field():
    """VMR must never return a confidence, probability, or score — deterministic only."""
    from app.services.vmr import resolve
    result = resolve("razia-bibi", {"package_color": "white", "stripe_color": "blue"})
    d = result.to_dict()
    for forbidden_key in ("confidence", "probability", "score", "likelihood", "match_score"):
        assert forbidden_key not in d, f"VMR result must not include '{forbidden_key}'"


# ---------------------------------------------------------------------------
# 10–11  Call context
# ---------------------------------------------------------------------------

def test_call_context_includes_only_verified_cues():
    """Call context variables must contain only cues from the database."""
    from app.services.call_context import build_call_context
    ctx = build_call_context("razia-bibi", "metformin-500")
    cue_list = ctx.variables.get("cue_list", "")
    # Must include verified metformin cues
    assert "stripe_color=blue" in cue_list
    assert "package_color=white" in cue_list
    # Must not contain anything fabricated
    assert "red" not in cue_list, "Amlodipine cues must not appear in Metformin context"


def test_patient_nickname_is_separate_from_clinical_name():
    """
    Razia Bibi knows her medicine as 'raat wali goli' — the context must keep
    this nickname distinct from the clinical name 'Metformin'.
    """
    from app.services.call_context import build_call_context
    ctx = build_call_context("razia-bibi", "metformin-500")
    assert ctx.variables["nickname"] == "raat wali goli"
    assert ctx.variables["clinical_name"] == "Metformin"
    assert ctx.variables["nickname"] != ctx.variables["clinical_name"]


# ---------------------------------------------------------------------------
# 12–15  demo-call endpoint behaviour
# ---------------------------------------------------------------------------

@patch("app.services.scheduler.httpx.AsyncClient")
def test_variables_within_documented_size_limit(mock_client_class, monkeypatch):
    """variables JSON must stay under 3000 chars (documented Uplift limit)."""
    mock_client_class.return_value = _mock_uplift_call()
    client = _make_p1_client(monkeypatch)
    response = client.post(
        "/api/dawa/demo-call",
        json={"patientId": "razia-bibi", "medicationId": "metformin-500"},
    )
    assert response.status_code == 200
    # Verify the call context directly
    from app.services.call_context import build_call_context
    ctx = build_call_context("razia-bibi", "metformin-500")
    size = len(json.dumps(ctx.variables, ensure_ascii=False))
    assert size <= 3000, f"variables JSON is {size} chars (limit 3000)"


@patch("app.services.scheduler.httpx.AsyncClient")
def test_instructions_within_documented_size_limit(mock_client_class, monkeypatch):
    """additionalInstructions must stay under 2000 chars (documented Uplift limit)."""
    mock_client_class.return_value = _mock_uplift_call()
    client = _make_p1_client(monkeypatch)
    from app.services.call_context import build_call_context
    ctx = build_call_context("razia-bibi", "metformin-500")
    size = len(ctx.additional_instructions)
    assert size <= 2000, f"additionalInstructions is {size} chars (limit 2000)"


@patch("app.services.scheduler.httpx.AsyncClient")
def test_demo_call_uses_uplift_assistant_id_not_request(mock_client_class, monkeypatch):
    """
    demo-call must use the patient's own assistant, chosen server-side.
    The caller cannot override it.
    """
    captured: dict = {}

    async def capture_post(url, json=None, **kwargs):
        captured.update(json or {})
        resp = MagicMock()
        resp.is_success = True
        resp.json.return_value = {"callId": "cap-call-id"}
        return resp

    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.post = capture_post
    mock_client_class.return_value = mock

    client = _make_p1_client(monkeypatch, assistant_id="asst-p1-test-123")
    response = client.post(
        "/api/dawa/demo-call",
        json={"patientId": "razia-bibi", "medicationId": "metformin-500"},
    )
    assert response.status_code == 200
    from tests.conftest import TEST_ASSISTANT_ID
    assert captured.get("assistantId") == TEST_ASSISTANT_ID


@patch("app.services.scheduler.httpx.AsyncClient")
def test_demo_call_uses_test_phone_number_not_request(mock_client_class, monkeypatch):
    """
    demo-call must always use TEST_PHONE_NUMBER from server settings.
    The request body cannot supply or override the destination phone.
    """
    captured: dict = {}

    async def capture_post(url, json=None, **kwargs):
        captured.update(json or {})
        resp = MagicMock()
        resp.is_success = True
        resp.json.return_value = {"callId": "cap-phone-id"}
        return resp

    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.post = capture_post
    mock_client_class.return_value = mock

    client = _make_p1_client(monkeypatch, phone="+923001234567")
    response = client.post(
        "/api/dawa/demo-call",
        json={"patientId": "razia-bibi", "medicationId": "metformin-500"},
    )
    assert response.status_code == 200
    assert captured.get("to") == "+923001234567"


@patch("app.services.scheduler.httpx.AsyncClient")
def test_demo_call_has_idempotency_key_header(mock_client_class, monkeypatch):
    """Every Uplift /calls POST must include an Idempotency-Key header."""
    captured_headers: dict = {}

    async def capture_post(url, json=None, headers=None, **kwargs):
        captured_headers.update(headers or {})
        resp = MagicMock()
        resp.is_success = True
        resp.json.return_value = {"callId": "idemp-call-id"}
        return resp

    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.post = capture_post
    mock_client_class.return_value = mock

    client = _make_p1_client(monkeypatch)
    client.post(
        "/api/dawa/demo-call",
        json={"patientId": "razia-bibi", "medicationId": "metformin-500"},
    )
    assert "Idempotency-Key" in captured_headers, (
        "Uplift /calls POST must include an Idempotency-Key header"
    )


# ---------------------------------------------------------------------------
# 16–17  P0-A conformance preserved
# ---------------------------------------------------------------------------

def test_p0a_health_route_still_returns_exact_shape(monkeypatch):
    """P0-A: GET /health must still return exactly {"status": "ok", "service": "dawa-p0"}."""
    client = _make_p1_client(monkeypatch)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "dawa-p0"}


@patch("app.services.uplift.httpx.AsyncClient")
def test_p0a_test_call_route_still_works(mock_client_class, monkeypatch):
    """P0-A: POST /api/test-call must still work with no auth and no body."""
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.get = AsyncMock(
        return_value=MagicMock(
            is_success=True,
            json=lambda: {"sessions": [{"callId": "p0a-call"}]},
        )
    )
    mock.post = AsyncMock(
        return_value=MagicMock(
            is_success=True,
            json=lambda: {"callId": "p0a-call"},
        )
    )
    mock_client_class.return_value = mock

    client = _make_p1_client(monkeypatch)
    resp = client.post("/api/test-call")
    assert resp.status_code == 200
    data = resp.json()
    assert "callId" in data
    assert "status" in data


# ---------------------------------------------------------------------------
# 18  Completed call ≠ adherence TAKEN
# ---------------------------------------------------------------------------

def test_completed_call_does_not_auto_set_adherence_to_taken():
    """
    A dose_event with call_status='completed' must NOT have adherenceOutcome='taken'.
    Completing the call only means the call ended — not that the patient took the medicine.
    """
    from app.services.dawa_store import create_dose_event, update_dose_event, get_recent_dose_events
    event = create_dose_event(
        patient_id="razia-bibi",
        medication_id="metformin-500",
        scheduled_time="21:00",
        call_id="test-call-completed",
        call_status="dispatched",
    )
    # Simulate Uplift reporting the call as completed
    update_dose_event(event["id"], call_status="completed")

    events = get_recent_dose_events(patient_id="razia-bibi", limit=5)
    updated = next(e for e in events if e["id"] == event["id"])

    assert updated["callStatus"] == "completed"
    assert updated["adherenceOutcome"] is None, (
        "Completing a call must NOT automatically set adherenceOutcome. "
        f"Got: {updated['adherenceOutcome']!r}"
    )
