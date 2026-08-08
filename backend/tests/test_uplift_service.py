"""
Tests for the Uplift service layer — P0-A paths.

Covers:
  - Config validation (UPLIFTAI_API_KEY required)
  - dispatch_call(): happy path, missing config, Uplift error codes
  - get_call_status(): session normalisation
  - _build_instructions(): safety and content checks

ALL Uplift HTTP requests are mocked — no real calls are placed, zero credits consumed.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(
    monkeypatch,
    *,
    assistant_id: str | None = "asst-test-123",
    phone: str | None = "+923001234567",
):
    """Create a P0-A TestClient with controlled env vars."""
    monkeypatch.setenv("UPLIFTAI_API_KEY", "test-api-key-xyz")
    if assistant_id is not None:
        monkeypatch.setenv("UPLIFT_ASSISTANT_ID", assistant_id)
    else:
        monkeypatch.delenv("UPLIFT_ASSISTANT_ID", raising=False)
    if phone is not None:
        monkeypatch.setenv("TEST_PHONE_NUMBER", phone)
    else:
        monkeypatch.delenv("TEST_PHONE_NUMBER", raising=False)
    # Clear future-phase secrets — they must not affect P0-A behaviour
    monkeypatch.delenv("DAWA_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("UPLIFT_WEBHOOK_SECRET", raising=False)

    import importlib
    import app.config as cfg_mod
    import app.services.uplift as svc_mod
    import app.api.test_call as api_mod
    import app.main as main_mod

    importlib.reload(cfg_mod)
    importlib.reload(svc_mod)
    importlib.reload(api_mod)
    importlib.reload(main_mod)

    from app.main import app  # noqa: PLC0415
    return TestClient(app)


def _mock_httpx_response(status_code: int, body: dict):
    mock = MagicMock()
    mock.status_code = status_code
    mock.is_success = (200 <= status_code < 300)
    mock.json.return_value = body
    mock.text = json.dumps(body)
    return mock


def _mock_call_http(*, call_status: int = 200, call_body: dict | None = None):
    """
    Build a reusable AsyncMock for dispatch_call().
    P0-A dispatch_call() makes exactly ONE POST to /calls.
    """
    if call_body is None:
        call_body = {"callId": "call-test"}
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.post = AsyncMock(return_value=_mock_httpx_response(call_status, call_body))
    return mock


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def test_missing_api_key_raises_on_import(monkeypatch):
    """Settings must raise if UPLIFTAI_API_KEY is absent."""
    monkeypatch.delenv("UPLIFTAI_API_KEY", raising=False)
    monkeypatch.delenv("UPLIFT_ASSISTANT_ID", raising=False)
    monkeypatch.delenv("TEST_PHONE_NUMBER", raising=False)

    import importlib
    import app.config as cfg_mod

    with pytest.raises(Exception):
        importlib.reload(cfg_mod)


# ---------------------------------------------------------------------------
# POST /api/test-call — happy path
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_call_success(mock_client_class, monkeypatch):
    """POST /api/test-call must return {callId, status} on success."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http(call_body={"callId": "call-abc"})

    response = client.post("/api/test-call")
    assert response.status_code == 200
    data = response.json()
    assert data["callId"] == "call-abc"
    assert data["status"] == "dispatched"
    # P0-A must not include medication or logId
    assert "medication" not in data
    assert "logId" not in data


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_call_unknown_call_id_fallback(mock_client_class, monkeypatch):
    """If Uplift response contains no callId field, dispatch_call returns 'unknown'."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http(call_body={})

    response = client.post("/api/test-call")
    assert response.status_code == 200
    data = response.json()
    assert data["callId"] == "unknown"
    assert data["status"] == "dispatched"


# ---------------------------------------------------------------------------
# POST /api/test-call — missing config
# ---------------------------------------------------------------------------

def test_dispatch_call_no_assistant_id_returns_503(monkeypatch):
    """POST /api/test-call must return 503 when UPLIFT_ASSISTANT_ID is absent."""
    client = _make_client(monkeypatch, assistant_id=None)
    response = client.post("/api/test-call")
    assert response.status_code == 503
    assert "UPLIFT_ASSISTANT_ID" in response.json()["detail"]


def test_dispatch_call_no_phone_returns_503(monkeypatch):
    """POST /api/test-call must return 503 when TEST_PHONE_NUMBER is absent."""
    client = _make_client(monkeypatch, phone=None)
    response = client.post("/api/test-call")
    assert response.status_code == 503
    assert "TEST_PHONE_NUMBER" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/test-call — Uplift error codes
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_call_uplift_402(mock_client_class, monkeypatch):
    """Uplift 402 must surface as 402 (insufficient credits)."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http(
        call_status=402, call_body={"message": "no credits"}
    )
    response = client.post("/api/test-call")
    assert response.status_code == 402


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_call_uplift_409(mock_client_class, monkeypatch):
    """Uplift 409 (number busy or duplicate call) must surface as 409."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http(
        call_status=409, call_body={"message": "call in flight"}
    )
    response = client.post("/api/test-call")
    assert response.status_code == 409


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_call_uplift_429(mock_client_class, monkeypatch):
    """Uplift 429 (rate limit) must surface as 429."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http(
        call_status=429, call_body={"message": "too many requests"}
    )
    response = client.post("/api/test-call")
    assert response.status_code == 429


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_call_uplift_404(mock_client_class, monkeypatch):
    """Uplift 404 must surface as 404 (UPLIFT_ASSISTANT_ID not found)."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http(
        call_status=404, call_body={"message": "assistant not found"}
    )
    response = client.post("/api/test-call")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/test-call/status — session normalisation
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_session_normalisation(mock_client_class, monkeypatch):
    """GET /api/test-call/status must return normalised session fields."""
    client = _make_client(monkeypatch)

    raw_sessions = {
        "sessions": [
            {
                "sessionId": "sess-001",
                "callId": "call-001",
                "status": "completed",
                "dispatched": True,
                "ringing": True,
                "answered": True,
                "completed": True,
                "failed": False,
                "failureReason": None,
                "startedAt": "2024-01-01T10:00:00Z",
                "endedAt": "2024-01-01T10:05:00Z",
            }
        ]
    }
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=_mock_httpx_response(200, raw_sessions))
    mock_client_class.return_value = mock_http

    response = client.get("/api/test-call/status")
    assert response.status_code == 200
    sessions = response.json()
    assert isinstance(sessions, list)
    assert len(sessions) == 1
    s = sessions[0]
    assert s["sessionId"] == "sess-001"
    assert s["status"] == "completed"
    assert s["answered"] is True
    assert s["failed"] is False


@patch("app.services.uplift.httpx.AsyncClient")
def test_status_returns_empty_list_when_no_sessions(mock_client_class, monkeypatch):
    """GET /api/test-call/status returns [] when Uplift returns no sessions."""
    client = _make_client(monkeypatch)
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=_mock_httpx_response(200, {"sessions": []}))
    mock_client_class.return_value = mock_http

    response = client.get("/api/test-call/status")
    assert response.status_code == 200
    assert response.json() == []


def test_status_no_assistant_id_returns_503(monkeypatch):
    """GET /api/test-call/status must return 503 when UPLIFT_ASSISTANT_ID is absent."""
    client = _make_client(monkeypatch, assistant_id=None)
    response = client.get("/api/test-call/status")
    assert response.status_code == 503
    assert "UPLIFT_ASSISTANT_ID" in response.json()["detail"]


# ---------------------------------------------------------------------------
# _build_instructions — safety and content
# ---------------------------------------------------------------------------

def test_build_instructions_contains_medication():
    """_build_instructions must embed the medication name in the output."""
    import importlib
    import app.services.uplift as svc_mod
    importlib.reload(svc_mod)

    instructions = svc_mod._build_instructions("Metformin")
    assert "Metformin" in instructions


def test_build_instructions_no_medical_advice():
    """Instructions must explicitly prohibit medical advice (Urdu phrase present)."""
    import importlib
    import app.services.uplift as svc_mod
    importlib.reload(svc_mod)

    instructions = svc_mod._build_instructions("Aspirin")
    assert "طبی معلومات" in instructions


def test_build_instructions_nahin_response_is_neutral():
    """
    The 'nahin' (no) branch must NOT tell the patient to take their medicine.
    It must suggest contacting their doctor instead.
    """
    import importlib
    import app.services.uplift as svc_mod
    importlib.reload(svc_mod)

    instructions = svc_mod._build_instructions("Metformin")

    assert "لینا ضروری ہے" not in instructions, (
        "The 'nahin' response must not tell the patient that taking medicine is necessary."
    )
    assert "ڈاکٹر" in instructions, (
        "The 'nahin' response must suggest the patient contacts their doctor."
    )
