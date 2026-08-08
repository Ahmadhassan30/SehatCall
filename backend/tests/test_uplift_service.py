"""
Tests for the Uplift service layer and /api/test-call* endpoints.

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

def _make_client(monkeypatch, *, assistant_id: str | None = "asst-test-123", phone: str | None = "+923001234567"):
    """Create a TestClient with controlled env vars."""
    monkeypatch.setenv("UPLIFTAI_API_KEY", "test-api-key-xyz")
    if assistant_id is not None:
        monkeypatch.setenv("UPLIFT_ASSISTANT_ID", assistant_id)
    else:
        monkeypatch.delenv("UPLIFT_ASSISTANT_ID", raising=False)
    if phone is not None:
        monkeypatch.setenv("TEST_PHONE_NUMBER", phone)
    else:
        monkeypatch.delenv("TEST_PHONE_NUMBER", raising=False)

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
    """Return a mock httpx.Response-like object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.is_success = (200 <= status_code < 300)
    mock.json.return_value = body
    mock.text = json.dumps(body)
    return mock


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------

def test_missing_api_key_raises_on_import(monkeypatch):
    """Settings must fail fast if UPLIFTAI_API_KEY is absent."""
    monkeypatch.delenv("UPLIFTAI_API_KEY", raising=False)
    import importlib
    import app.config as cfg_mod
    with pytest.raises(Exception):
        importlib.reload(cfg_mod)


def test_optional_secrets_do_not_raise_on_import(monkeypatch):
    """Server should load fine with only UPLIFTAI_API_KEY set."""
    monkeypatch.setenv("UPLIFTAI_API_KEY", "key-only")
    monkeypatch.delenv("UPLIFT_ASSISTANT_ID", raising=False)
    monkeypatch.delenv("TEST_PHONE_NUMBER", raising=False)
    import importlib
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    assert cfg_mod.settings.uplift_assistant_id is None
    assert cfg_mod.settings.test_phone_number is None


# ---------------------------------------------------------------------------
# Singapore base URL tests
# ---------------------------------------------------------------------------

def test_singapore_base_url():
    """The Uplift base URL must use the Singapore (ap-southeast-1) region."""
    from app.config import UPLIFT_BASE_URL  # noqa: PLC0415
    assert "ap-southeast-1" in UPLIFT_BASE_URL
    assert UPLIFT_BASE_URL.startswith("https://ap-southeast-1.api.upliftai.org")


def test_base_url_not_us_region():
    """The US endpoint must not be used for Pakistani calls."""
    from app.config import UPLIFT_BASE_URL  # noqa: PLC0415
    assert "us-east" not in UPLIFT_BASE_URL
    assert "us-west" not in UPLIFT_BASE_URL


# ---------------------------------------------------------------------------
# Dispatch call — payload formation
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_call_payload(mock_client_class, monkeypatch):
    """Outbound call must send correct assistantId and to fields."""
    client = _make_client(monkeypatch, assistant_id="asst-abc", phone="+923009876543")

    mock_response = _mock_httpx_response(200, {"callId": "call-001"})
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_http

    response = client.post("/api/test-call")
    assert response.status_code == 200

    call_args = mock_http.post.call_args
    payload = call_args.kwargs.get("json") or call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["json"]
    assert payload["assistantId"] == "asst-abc"
    assert payload["to"] == "+923009876543"


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_call_idempotency_key(mock_client_class, monkeypatch):
    """Each call attempt must include an Idempotency-Key header."""
    client = _make_client(monkeypatch, assistant_id="asst-abc", phone="+923009876543")

    mock_response = _mock_httpx_response(200, {"callId": "call-002"})
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_http

    client.post("/api/test-call")

    call_args = mock_http.post.call_args
    headers = call_args.kwargs.get("headers", {})
    assert "Idempotency-Key" in headers
    assert headers["Idempotency-Key"]  # non-empty


# ---------------------------------------------------------------------------
# Authorization header tests
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_auth_header_present(mock_client_class, monkeypatch):
    """Authorization header must be present and Bearer-prefixed (value not exposed)."""
    client = _make_client(monkeypatch, assistant_id="asst-abc", phone="+923009876543")

    mock_response = _mock_httpx_response(200, {"callId": "call-003"})
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_http

    client.post("/api/test-call")

    call_args = mock_http.post.call_args
    headers = call_args.kwargs.get("headers", {})
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Bearer ")
    # Confirm the real key is not returned by the endpoint
    response = client.post("/api/test-call")
    assert "test-api-key-xyz" not in response.text


# ---------------------------------------------------------------------------
# Dispatched status passthrough
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatched_status_passthrough(mock_client_class, monkeypatch):
    """Response status must be 'dispatched', never 'answered' or 'successful'."""
    client = _make_client(monkeypatch, assistant_id="asst-abc", phone="+923009876543")

    mock_response = _mock_httpx_response(200, {"callId": "call-004"})
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_http

    response = client.post("/api/test-call")
    data = response.json()
    assert data["status"] == "dispatched"
    assert "answered" not in str(data).lower()
    assert "successful" not in str(data).lower()


# ---------------------------------------------------------------------------
# Missing secrets at call-time
# ---------------------------------------------------------------------------

def test_test_call_fails_without_assistant_id(monkeypatch):
    """POST /api/test-call must return 503 with clear message if UPLIFT_ASSISTANT_ID missing."""
    client = _make_client(monkeypatch, assistant_id=None, phone="+923009876543")
    response = client.post("/api/test-call")
    assert response.status_code == 503
    assert "UPLIFT_ASSISTANT_ID" in response.json()["detail"]


def test_test_call_fails_without_phone(monkeypatch):
    """POST /api/test-call must return 503 with clear message if TEST_PHONE_NUMBER missing."""
    client = _make_client(monkeypatch, assistant_id="asst-abc", phone=None)
    response = client.post("/api/test-call")
    assert response.status_code == 503
    assert "TEST_PHONE_NUMBER" in response.json()["detail"]


def test_status_fails_without_assistant_id(monkeypatch):
    """GET /api/test-call/status must return 503 if UPLIFT_ASSISTANT_ID missing."""
    client = _make_client(monkeypatch, assistant_id=None, phone=None)
    response = client.get("/api/test-call/status")
    assert response.status_code == 503
    assert "UPLIFT_ASSISTANT_ID" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Error normalisation
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_401_normalisation(mock_client_class, monkeypatch):
    """Uplift 401 must return 401 with clear message."""
    client = _make_client(monkeypatch)
    mock_response = _mock_httpx_response(401, {"message": "Unauthorized"})
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_http

    response = client.post("/api/test-call")
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower() or "key" in response.json()["detail"].lower()


@patch("app.services.uplift.httpx.AsyncClient")
def test_402_normalisation(mock_client_class, monkeypatch):
    """Uplift 402 must return 402 (insufficient credits)."""
    client = _make_client(monkeypatch)
    mock_response = _mock_httpx_response(402, {"message": "Insufficient credits"})
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_http

    response = client.post("/api/test-call")
    assert response.status_code == 402
    assert "credit" in response.json()["detail"].lower()


@patch("app.services.uplift.httpx.AsyncClient")
def test_409_normalisation(mock_client_class, monkeypatch):
    """Uplift 409 must return 409 (busy or duplicate in-flight)."""
    client = _make_client(monkeypatch)
    mock_response = _mock_httpx_response(409, {"message": "Number busy"})
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_http

    response = client.post("/api/test-call")
    assert response.status_code == 409


@patch("app.services.uplift.httpx.AsyncClient")
def test_429_normalisation(mock_client_class, monkeypatch):
    """Uplift 429 must return 429 (rate/concurrency limit)."""
    client = _make_client(monkeypatch)
    mock_response = _mock_httpx_response(429, {"message": "Too many requests"})
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_http

    response = client.post("/api/test-call")
    assert response.status_code == 429


# ---------------------------------------------------------------------------
# Session / status normalisation
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
    mock_response = _mock_httpx_response(200, raw_sessions)
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=mock_response)
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
