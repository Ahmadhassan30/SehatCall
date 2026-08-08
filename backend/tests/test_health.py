"""
Tests for the /health endpoint.

These tests do NOT call Uplift APIs and consume zero credits.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    """Return a TestClient with UPLIFTAI_API_KEY faked so Settings loads."""
    monkeypatch.setenv("UPLIFTAI_API_KEY", "test-key-health")
    # Re-import app after env is patched so Settings re-initialises
    import importlib
    import app.config as cfg_mod
    import app.main as main_mod

    importlib.reload(cfg_mod)
    importlib.reload(main_mod)

    from app.main import app  # noqa: PLC0415
    return TestClient(app)


def test_health_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_body(client):
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "dawa-p0"


def test_health_works_without_assistant_id(monkeypatch):
    """Server must boot and /health must succeed even with UPLIFT_ASSISTANT_ID absent."""
    monkeypatch.setenv("UPLIFTAI_API_KEY", "test-key-no-assistant")
    monkeypatch.delenv("UPLIFT_ASSISTANT_ID", raising=False)
    monkeypatch.delenv("TEST_PHONE_NUMBER", raising=False)

    import importlib
    import app.config as cfg_mod
    import app.main as main_mod

    importlib.reload(cfg_mod)
    importlib.reload(main_mod)

    from app.main import app  # noqa: PLC0415
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
