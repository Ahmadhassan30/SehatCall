"""
P0-A Conformance Tests for DAWA.

These 15 tests verify that the backend strictly conforms to the P0-A spec:
  - GET /health            → {"status": "ok", "service": "dawa-p0"} — nothing else
  - POST /api/test-call    → no auth, no body, {"callId", "status"} only
  - GET /api/test-call/status → no auth, queries Uplift directly
  - Bootstrap script path  → correct Singapore endpoint, correct payload, no /calls POST
  - Future routes          → GET /api/call-log and POST /api/webhook/call-complete return 404

ALL Uplift HTTP requests are mocked — no real calls are placed, zero credits consumed.
No real assistants are created.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_httpx_response(status_code: int, body: dict):
    mock = MagicMock()
    mock.status_code = status_code
    mock.is_success = (200 <= status_code < 300)
    mock.json.return_value = body
    mock.text = json.dumps(body)
    return mock


def _make_client(
    monkeypatch,
    *,
    assistant_id: str | None = "asst-p0a-test-123",
    phone: str | None = "+923001234567",
):
    """Create a P0-A TestClient with controlled env vars."""
    monkeypatch.setenv("UPLIFTAI_API_KEY", "test-api-key-p0a")
    if assistant_id is not None:
        monkeypatch.setenv("UPLIFT_ASSISTANT_ID", assistant_id)
    else:
        monkeypatch.delenv("UPLIFT_ASSISTANT_ID", raising=False)
    if phone is not None:
        monkeypatch.setenv("TEST_PHONE_NUMBER", phone)
    else:
        monkeypatch.delenv("TEST_PHONE_NUMBER", raising=False)
    # Clear future-phase secrets so they don't affect P0-A behaviour
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


def _mock_call_http(call_body: dict | None = None):
    """One POST to /calls — the only HTTP call in P0-A dispatch_call()."""
    call_body = call_body or {"callId": "call-p0a-test"}
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.post = AsyncMock(return_value=_mock_httpx_response(200, call_body))
    return mock


# ---------------------------------------------------------------------------
# 1. GET /health — exact response shape
# ---------------------------------------------------------------------------

def test_health_returns_200(monkeypatch):
    """GET /health must return HTTP 200."""
    client = _make_client(monkeypatch)
    assert client.get("/health").status_code == 200


def test_health_exact_response_shape(monkeypatch):
    """
    GET /health must return exactly {"status": "ok", "service": "dawa-p0"}.
    No warnings key, no extra fields.
    """
    client = _make_client(monkeypatch)
    data = client.get("/health").json()
    assert data == {"status": "ok", "service": "dawa-p0"}, (
        f"Expected exactly {{status, service}}, got: {data}"
    )


def test_health_no_warnings_key(monkeypatch):
    """GET /health must never include a 'warnings' key in P0-A."""
    client = _make_client(monkeypatch)
    data = client.get("/health").json()
    assert "warnings" not in data, (
        "'warnings' key must not appear in P0-A /health response"
    )


# ---------------------------------------------------------------------------
# 2. POST /api/test-call — no auth, no body, correct response shape
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_requires_no_authentication(mock_client_class, monkeypatch):
    """POST /api/test-call must succeed with no Authorization or X-Admin-Token header."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http()
    # Explicitly send no auth headers
    response = client.post("/api/test-call")
    assert response.status_code == 200, (
        f"P0-A must accept POST /api/test-call with no auth header; got {response.status_code}"
    )


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_accepts_empty_body(mock_client_class, monkeypatch):
    """POST /api/test-call must succeed with no request body."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http()
    response = client.post("/api/test-call")
    assert response.status_code == 200


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_response_contains_only_call_id_and_status(mock_client_class, monkeypatch):
    """
    POST /api/test-call response must contain exactly {callId, status}.
    No medication, logId, or other extra fields.
    """
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http({"callId": "call-shape-test"})
    data = client.post("/api/test-call").json()
    assert set(data.keys()) == {"callId", "status"}, (
        f"P0-A response must have exactly {{callId, status}}; got keys: {set(data.keys())}"
    )


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_status_value_is_dispatched(mock_client_class, monkeypatch):
    """POST /api/test-call response['status'] must equal 'dispatched'."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http({"callId": "call-status-test"})
    data = client.post("/api/test-call").json()
    assert data["status"] == "dispatched"


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_response_contains_no_medication(mock_client_class, monkeypatch):
    """POST /api/test-call response must NOT contain a 'medication' field."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http()
    data = client.post("/api/test-call").json()
    assert "medication" not in data, "P0-A response must not expose medication field"


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_response_contains_no_log_id(mock_client_class, monkeypatch):
    """POST /api/test-call response must NOT contain a 'logId' field."""
    client = _make_client(monkeypatch)
    mock_client_class.return_value = _mock_call_http()
    data = client.post("/api/test-call").json()
    assert "logId" not in data, "P0-A response must not expose logId field"


# ---------------------------------------------------------------------------
# 3. Service purity — UPLIFT_ASSISTANT_ID, no assistant creation
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_uses_uplift_assistant_id_directly(mock_client_class, monkeypatch):
    """
    dispatch_call() must send settings.uplift_assistant_id in the /calls payload.
    It must NOT send a dynamically created assistant ID.
    """
    expected_id = "asst-p0a-test-123"
    client = _make_client(monkeypatch, assistant_id=expected_id)
    mock_http = _mock_call_http({"callId": "call-asst-check"})
    mock_client_class.return_value = mock_http

    response = client.post("/api/test-call")
    assert response.status_code == 200

    call_args = mock_http.post.call_args
    sent_body = call_args.kwargs.get("json") or {}
    assert sent_body.get("assistantId") == expected_id, (
        f"Expected assistantId={expected_id!r} in /calls payload, got {sent_body.get('assistantId')!r}"
    )


@patch("app.services.uplift.httpx.AsyncClient")
def test_dispatch_does_not_create_assistant(mock_client_class, monkeypatch):
    """
    dispatch_call() must make exactly ONE POST (to /calls).
    It must NEVER POST to /realtime-assistants.
    """
    client = _make_client(monkeypatch)
    mock_http = _mock_call_http({"callId": "call-one-post"})
    mock_client_class.return_value = mock_http

    response = client.post("/api/test-call")
    assert response.status_code == 200

    assert mock_http.post.call_count == 1, (
        f"Expected exactly 1 POST (to /calls); got {mock_http.post.call_count}"
    )
    call_url = mock_http.post.call_args.args[0] if mock_http.post.call_args.args else \
               mock_http.post.call_args.kwargs.get("url", "")
    assert "/calls" in call_url, f"The single POST must target /calls; got {call_url!r}"
    assert "realtime-assistants" not in call_url, (
        "dispatch_call() must not POST to /realtime-assistants in P0-A"
    )


def test_dispatch_missing_assistant_id_returns_503(monkeypatch):
    """POST /api/test-call must return 503 when UPLIFT_ASSISTANT_ID is not set."""
    client = _make_client(monkeypatch, assistant_id=None)
    response = client.post("/api/test-call")
    assert response.status_code == 503
    assert "UPLIFT_ASSISTANT_ID" in response.json()["detail"]


def test_dispatch_missing_phone_number_returns_503(monkeypatch):
    """POST /api/test-call must return 503 when TEST_PHONE_NUMBER is not set."""
    client = _make_client(monkeypatch, phone=None)
    response = client.post("/api/test-call")
    assert response.status_code == 503
    assert "TEST_PHONE_NUMBER" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 4. GET /api/test-call/status — no auth
# ---------------------------------------------------------------------------

@patch("app.services.uplift.httpx.AsyncClient")
def test_status_endpoint_requires_no_authentication(mock_client_class, monkeypatch):
    """GET /api/test-call/status must return 200 with no auth header (mocked Uplift)."""
    client = _make_client(monkeypatch)
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(
        return_value=_mock_httpx_response(200, {"sessions": []})
    )
    mock_client_class.return_value = mock_http

    response = client.get("/api/test-call/status")
    assert response.status_code == 200, (
        "GET /api/test-call/status must be accessible with no auth header in P0-A"
    )


# ---------------------------------------------------------------------------
# 5. Bootstrap script validation (mocked HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bootstrap_uses_singapore_endpoint_and_returns_assistant_id(monkeypatch):
    """
    create_assistant() must:
      - POST to the Singapore Uplift endpoint (ap-southeast-1.api.upliftai.org)
      - Include exactly one POST to /realtime-assistants
      - Parse and return the realtimeAssistantId from the response
      - NOT POST to /calls
    """
    monkeypatch.setenv("UPLIFTAI_API_KEY", "test-bootstrap-key")
    monkeypatch.setenv("UPLIFT_ASSISTANT_ID", "asst-unused-in-bootstrap")

    import importlib
    import app.config as cfg_mod
    import app.services.uplift as svc_mod

    importlib.reload(cfg_mod)
    importlib.reload(svc_mod)

    fake_response = _mock_httpx_response(200, {"realtimeAssistantId": "asst-bootstrap-xyz"})

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=fake_response)

    with patch("app.services.uplift.httpx.AsyncClient", return_value=mock_http):
        result = await svc_mod.create_assistant(name="DAWA Bootstrap Test")

    # realtimeAssistantId must be parsed
    assert result.get("realtimeAssistantId") == "asst-bootstrap-xyz", (
        f"create_assistant must return the realtimeAssistantId; got {result}"
    )

    # Exactly one POST must have been made
    assert mock_http.post.call_count == 1, (
        f"Bootstrap must make exactly 1 POST; got {mock_http.post.call_count}"
    )

    # That POST must target /realtime-assistants on the Singapore endpoint
    posted_url = mock_http.post.call_args.args[0] if mock_http.post.call_args.args else \
                 mock_http.post.call_args.kwargs.get("url", "")
    assert "ap-southeast-1.api.upliftai.org" in posted_url, (
        f"Bootstrap must use Singapore endpoint; got {posted_url!r}"
    )
    assert "realtime-assistants" in posted_url, (
        f"Bootstrap must POST to /realtime-assistants; got {posted_url!r}"
    )
    assert "/calls" not in posted_url, (
        "Bootstrap must NOT POST to /calls"
    )


# ---------------------------------------------------------------------------
# 6. Future routes must be unreachable
# ---------------------------------------------------------------------------

def test_future_routes_are_not_registered(monkeypatch):
    """
    GET /api/call-log and POST /api/webhook/call-complete must return 404 in P0-A.
    These routes live in future_calls.py and must NOT be registered in the app.
    """
    client = _make_client(monkeypatch)

    call_log_resp = client.get("/api/call-log")
    assert call_log_resp.status_code == 404, (
        f"GET /api/call-log must be unreachable in P0-A; got {call_log_resp.status_code}"
    )

    webhook_resp = client.post(
        "/api/webhook/call-complete",
        json={"callId": "call-probe", "status": "completed"},
    )
    assert webhook_resp.status_code == 404, (
        f"POST /api/webhook/call-complete must be unreachable in P0-A; got {webhook_resp.status_code}"
    )
