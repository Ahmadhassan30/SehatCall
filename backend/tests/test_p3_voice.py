"""
DAWA P3 — DAWA voice selection (30 tests).

Coverage:
   1-6   verified catalog integrity (no invented voice IDs)
   7-11  GET /voices
  12-19  PUT /patient/voice ordering, validation, rollback, 409 during a call
  20-24  update_assistant_voice payload shape (TTS only, complete object)
  25-28  preview endpoint (fixed phrase, server-side key, caching)
  29-30  ensure_preferred_voice drift guard

ALL Uplift HTTP calls are mocked — no real calls are placed and no assistant
is ever created or mutated for real.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import seed_test_patient
from fastapi import HTTPException
from fastapi.testclient import TestClient


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


@pytest.fixture
def assistant_id(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "uplift_assistant_id", "asst-test-123", raising=False)
    return "asst-test-123"


def _ok_response(content: bytes = b"", status: int = 200):
    r = MagicMock()
    r.is_success = status < 400
    r.status_code = status
    r.content = content
    r.json.return_value = {}
    r.text = ""
    return r


# ---------------------------------------------------------------------------
# 1-6  Catalog integrity
# ---------------------------------------------------------------------------

def test_01_catalog_has_a_reasonable_number_of_voices():
    from app.services import voice_catalog
    n = len(voice_catalog.list_voices())
    assert 6 <= n <= 12, f"expected a curated 6-12 voice catalog, got {n}"


def test_02_every_voice_has_id_name_language():
    from app.services import voice_catalog
    for v in voice_catalog.list_voices():
        assert v["id"] and isinstance(v["id"], str)
        assert v["name"] and isinstance(v["name"], str)
        assert v["language"]


def test_03_voice_ids_are_unique():
    from app.services import voice_catalog
    ids = [v["id"] for v in voice_catalog.list_voices()]
    assert len(ids) == len(set(ids))


def test_04_default_voice_is_the_current_production_voice():
    """Enabling voice selection must not change how DAWA already sounds."""
    from app.services import voice_catalog
    assert voice_catalog.DEFAULT_VOICE_ID == "helpdesk-agent"
    assert voice_catalog.is_valid_voice(voice_catalog.DEFAULT_VOICE_ID)


def test_05_validation_rejects_unknown_and_injected_ids():
    from app.services import voice_catalog
    for bad in ("", "made-up-voice", "v_notreal", "../etc/passwd", "helpdesk agent"):
        assert not voice_catalog.is_valid_voice(bad)


def test_06_catalog_exposes_no_secrets():
    import json
    from app.services import voice_catalog
    raw = json.dumps(voice_catalog.list_voices()).lower()
    for leak in ("api_key", "apikey", "bearer", "authorization", "assistant"):
        assert leak not in raw


# ---------------------------------------------------------------------------
# 7-11  GET /voices
# ---------------------------------------------------------------------------

def test_07_get_voices_returns_catalog(client):
    body = client.get("/api/dawa/voices").json()
    assert len(body["voices"]) >= 6


def test_08_get_voices_reports_current_selection(client):
    assert client.get("/api/dawa/voices").json()["selectedVoiceId"] == "helpdesk-agent"


def test_09_seeded_patient_has_the_default_voice(client):
    p = client.get("/api/dawa/patient").json()
    assert p["preferredVoiceId"] == "helpdesk-agent"
    assert p["preferredVoiceName"]


def test_10_voice_seed_is_idempotent_and_respects_user_choice():
    from app.services import dawa_store
    dawa_store.set_patient_voice("razia-bibi", "v_yypgzenx", "Urdu — Dada Jee")
    seed_test_patient()  # must not reset the caregiver's choice
    assert dawa_store.get_patient("razia-bibi")["preferred_voice_id"] == "v_yypgzenx"


def test_11_voices_endpoint_needs_no_uplift_call(client):
    """Listing voices must be local — never a live API dependency."""
    with patch("app.services.uplift.httpx.AsyncClient") as http:
        client.get("/api/dawa/voices")
    http.assert_not_called()


# ---------------------------------------------------------------------------
# 12-19  PUT /patient/voice
# ---------------------------------------------------------------------------

def test_12_set_voice_updates_uplift_then_persists(client, assistant_id):
    """The voice change must land on the PATIENT'S assistant, not the shared one."""
    from tests.conftest import TEST_ASSISTANT_ID

    with patch("app.services.uplift.update_assistant_voice",
               new=AsyncMock()) as upd:
        r = client.put("/api/dawa/patient/voice", json={"voiceId": "v_yypgzenx"})
    assert r.status_code == 200
    upd.assert_awaited_once_with("v_yypgzenx", assistant_id=TEST_ASSISTANT_ID)
    assert r.json()["preferredVoiceId"] == "v_yypgzenx"


def test_12b_set_voice_before_the_patient_has_an_assistant(client, assistant_id):
    """
    A patient who has never been dialled has no assistant yet. There is nothing
    remote to change — theirs is created carrying this voice on first dispatch —
    so the preference must still persist without an Uplift round trip.
    """
    from app.services.dawa_store import _connect, get_patient
    from tests.conftest import DEMO_PATIENT_ID

    with _connect() as conn:
        conn.execute(
            "UPDATE patients SET assistant_id = NULL WHERE id = ?", (DEMO_PATIENT_ID,)
        )

    with patch("app.services.uplift.update_assistant_voice", new=AsyncMock()) as upd:
        r = client.put("/api/dawa/patient/voice", json={"voiceId": "v_yypgzenx"})

    assert r.status_code == 200
    upd.assert_not_awaited()
    assert get_patient(DEMO_PATIENT_ID)["preferred_voice_id"] == "v_yypgzenx"


def test_13_set_voice_rejects_unknown_id(client):
    with patch("app.services.uplift.update_assistant_voice", new=AsyncMock()) as upd:
        r = client.put("/api/dawa/patient/voice", json={"voiceId": "not-a-voice"})
    assert r.status_code == 400
    upd.assert_not_awaited()  # never contact Uplift with junk


def test_14_set_voice_does_not_persist_when_uplift_fails(client, assistant_id):
    """The DB must never advertise a voice the assistant isn't using."""
    from app.services import dawa_store
    before = dawa_store.get_patient("razia-bibi")["preferred_voice_id"]
    with patch("app.services.uplift.update_assistant_voice",
               new=AsyncMock(side_effect=RuntimeError("uplift down"))):
        r = client.put("/api/dawa/patient/voice", json={"voiceId": "v_yypgzenx"})
    assert r.status_code == 502
    assert dawa_store.get_patient("razia-bibi")["preferred_voice_id"] == before


def test_15_failed_voice_change_tells_the_caregiver_the_old_voice_is_active(client, assistant_id):
    with patch("app.services.uplift.update_assistant_voice",
               new=AsyncMock(side_effect=RuntimeError("boom"))):
        r = client.put("/api/dawa/patient/voice", json={"voiceId": "v_yypgzenx"})
    assert "previous voice is still active" in r.json()["detail"].lower()


def test_16_set_voice_rejected_while_a_call_is_active(client, assistant_id):
    with patch("app.services.scheduler.has_active_call", return_value=True), \
         patch("app.services.uplift.update_assistant_voice", new=AsyncMock()) as upd:
        r = client.put("/api/dawa/patient/voice", json={"voiceId": "v_yypgzenx"})
    assert r.status_code == 409
    upd.assert_not_awaited()  # never swap voices mid-call


def test_17_set_voice_persists_the_display_name(client, assistant_id):
    from app.services import dawa_store, voice_catalog
    with patch("app.services.uplift.update_assistant_voice", new=AsyncMock()):
        client.put("/api/dawa/patient/voice", json={"voiceId": "v_30s70t3a"})
    p = dawa_store.get_patient("razia-bibi")
    assert p["preferred_voice_name"] == voice_catalog.voice_name("v_30s70t3a")


def test_18_set_voice_is_reflected_in_subsequent_reads(client, assistant_id):
    with patch("app.services.uplift.update_assistant_voice", new=AsyncMock()):
        client.put("/api/dawa/patient/voice", json={"voiceId": "v_8eelc901"})
    assert client.get("/api/dawa/voices").json()["selectedVoiceId"] == "v_8eelc901"
    assert client.get("/api/dawa/patient").json()["preferredVoiceId"] == "v_8eelc901"


def test_19_voice_change_does_not_touch_medication_data(client, assistant_id):
    from app.services import dawa_store
    before = dawa_store.get_medications_for_patient("razia-bibi")
    with patch("app.services.uplift.update_assistant_voice", new=AsyncMock()):
        client.put("/api/dawa/patient/voice", json={"voiceId": "v_kwmp7zxt"})
    assert dawa_store.get_medications_for_patient("razia-bibi") == before


# ---------------------------------------------------------------------------
# 20-24  update_assistant_voice payload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_20_update_sends_complete_tts_default_object(assistant_id):
    from app.services import uplift
    with patch.object(uplift, "httpx") as httpx_mod:
        cli = httpx_mod.AsyncClient.return_value.__aenter__.return_value
        cli.post = AsyncMock(return_value=_ok_response())
        await uplift.update_assistant_voice("v_yypgzenx")
        payload = cli.post.call_args.kwargs["json"]
    default = payload["config"]["tts"]["default"]
    assert default["voiceId"] == "v_yypgzenx"
    assert default["provider"] == "upliftai"
    assert default["outputFormat"] == "MP3_22050_32"


@pytest.mark.asyncio
async def test_21_update_touches_only_tts(assistant_id):
    """Agent instructions / STT / LLM / session config must be left alone."""
    from app.services import uplift
    with patch.object(uplift, "httpx") as httpx_mod:
        cli = httpx_mod.AsyncClient.return_value.__aenter__.return_value
        cli.post = AsyncMock(return_value=_ok_response())
        await uplift.update_assistant_voice("v_yypgzenx")
        payload = cli.post.call_args.kwargs["json"]
    assert set(payload["config"].keys()) == {"tts"}
    for forbidden in ("agent", "stt", "llm", "session", "instructions", "greeting"):
        assert forbidden not in payload
        assert forbidden not in payload["config"]


@pytest.mark.asyncio
async def test_22_update_uses_documented_post_endpoint(assistant_id):
    from app.services import uplift
    with patch.object(uplift, "httpx") as httpx_mod:
        cli = httpx_mod.AsyncClient.return_value.__aenter__.return_value
        cli.post = AsyncMock(return_value=_ok_response())
        await uplift.update_assistant_voice("v_yypgzenx")
        url = cli.post.call_args.args[0]
    assert url.endswith(f"/realtime-assistants/{assistant_id}")


@pytest.mark.asyncio
async def test_23_update_rejects_unknown_voice_before_any_request(assistant_id):
    from app.services import uplift
    with patch.object(uplift, "httpx") as httpx_mod:
        with pytest.raises(HTTPException) as exc:
            await uplift.update_assistant_voice("fake-voice")
        assert exc.value.status_code == 400
        httpx_mod.AsyncClient.assert_not_called()


@pytest.mark.asyncio
async def test_24_update_requires_a_configured_assistant(monkeypatch):
    from app.config import settings
    from app.services import uplift
    monkeypatch.setattr(settings, "uplift_assistant_id", "", raising=False)
    with pytest.raises(HTTPException) as exc:
        await uplift.update_assistant_voice("v_yypgzenx")
    assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# 25-28  Preview
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_25_preview_uses_a_fixed_server_side_phrase():
    from app.services import uplift, voice_catalog
    with patch.object(uplift, "httpx") as httpx_mod:
        cli = httpx_mod.AsyncClient.return_value.__aenter__.return_value
        cli.post = AsyncMock(return_value=_ok_response(b"ID3audio"))
        audio = await uplift.synthesize_voice_preview("v_yypgzenx")
        payload = cli.post.call_args.kwargs["json"]
        url = cli.post.call_args.args[0]
    assert audio == b"ID3audio"
    assert payload["text"] == voice_catalog.PREVIEW_PHRASE
    assert payload["voiceId"] == "v_yypgzenx"
    assert url.endswith("/synthesis/text-to-speech")


def test_26_preview_endpoint_returns_audio(client, tmp_path, monkeypatch):
    import app.api.dawa as dawa_api
    monkeypatch.setattr(dawa_api, "_VOICE_PREVIEW_CACHE", tmp_path / "cache")
    with patch("app.services.uplift.synthesize_voice_preview",
               new=AsyncMock(return_value=b"ID3audio")):
        r = client.post("/api/dawa/voices/v_yypgzenx/preview")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3audio"


def test_27_preview_rejects_unknown_voice_and_cannot_proxy_text(client):
    """Not usable as an open TTS proxy — no caller-supplied text is accepted."""
    with patch("app.services.uplift.synthesize_voice_preview", new=AsyncMock()) as syn:
        r = client.post("/api/dawa/voices/evil-voice/preview",
                        json={"text": "arbitrary text"})
    assert r.status_code == 400
    syn.assert_not_awaited()


def test_28_preview_is_cached_after_the_first_request(client, tmp_path, monkeypatch):
    import app.api.dawa as dawa_api
    monkeypatch.setattr(dawa_api, "_VOICE_PREVIEW_CACHE", tmp_path / "cache")
    with patch("app.services.uplift.synthesize_voice_preview",
               new=AsyncMock(return_value=b"ID3audio")) as syn:
        client.post("/api/dawa/voices/v_yypgzenx/preview")
        client.post("/api/dawa/voices/v_yypgzenx/preview")
    assert syn.await_count == 1  # second tap served from cache


# ---------------------------------------------------------------------------
# 29-30  Drift guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_29_ensure_preferred_voice_syncs_once_then_caches(assistant_id):
    from app.services import dawa_store, scheduler as sched
    dawa_store.set_patient_voice("razia-bibi", "v_yypgzenx", "Urdu — Dada Jee")
    with patch.object(sched.uplift_service, "update_assistant_voice",
                      new=AsyncMock()) as upd:
        await sched.ensure_preferred_voice("razia-bibi")
        await sched.ensure_preferred_voice("razia-bibi")
    assert upd.await_count == 1


@pytest.mark.asyncio
async def test_30_voice_sync_failure_never_blocks_the_reminder(assistant_id):
    """A cosmetic voice problem must not stop a medication call going out."""
    from app.services import dawa_store, scheduler as sched
    dawa_store.set_patient_voice("razia-bibi", "v_yypgzenx", "Urdu — Dada Jee")
    with patch.object(sched.uplift_service, "update_assistant_voice",
                      new=AsyncMock(side_effect=RuntimeError("uplift down"))):
        result = await sched.ensure_preferred_voice("razia-bibi")  # must not raise
    assert result == "v_yypgzenx"
