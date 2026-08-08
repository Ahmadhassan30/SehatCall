"""
Uplift AI service layer for DAWA.

All HTTP communication with the Uplift API is centralised here.
No raw Uplift calls should appear in route handlers.

Singapore endpoint (ap-southeast-1) is used exclusively — this is the only
region that supports outbound calls to Pakistani phone numbers.

─────────────────────────────────────────────
P0-A CANONICAL FUNCTIONS (used by test_call.py)
─────────────────────────────────────────────
  dispatch_call()   — place one call using UPLIFT_ASSISTANT_ID from settings
  get_call_status() — fetch recent sessions from Uplift (no SQLite merge)

─────────────────────────────────────────────
FUTURE-PHASE HELPERS (preserved, not called by P0-A paths)
─────────────────────────────────────────────
  create_assistant()                    — bootstrap script only
  get_or_create_medication_assistant()  — P0-B per-medication caching
  update_assistant_instructions()       — P0-B shared-assistant PATCH path
  get_call_log()                        — used by future_calls.GET /api/call-log
  _append_call_log()                    — used by future-phase dispatch
  _build_instructions()                 — used by create_assistant
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import UPLIFT_BASE_URL, settings

logger = logging.getLogger("dawa.uplift")


# ---------------------------------------------------------------------------
# Phone number masking helper
# ---------------------------------------------------------------------------

def _mask_phone(number: str) -> str:
    """Mask a phone number for safe logging, e.g. +92XXXXXXX4567."""
    if len(number) <= 6:
        return "***"
    return number[:3] + "*" * (len(number) - 6) + number[-4:]


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------

def _auth_headers() -> dict[str, str]:
    """Return the Authorization + Content-Type headers required by Uplift."""
    return {
        "Authorization": f"Bearer {settings.upliftai_api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Error normalisation
# ---------------------------------------------------------------------------

def _raise_for_uplift_error(response: httpx.Response) -> None:
    """Translate Uplift HTTP error codes into descriptive FastAPI HTTPExceptions."""
    if response.is_success:
        return

    status = response.status_code
    try:
        body = response.json()
        uplift_message = body.get("message") or body.get("error") or str(body)
    except Exception:
        uplift_message = response.text or "(no body)"

    logger.warning(
        "UPLIFT_API_ERROR",
        extra={"http_status": status, "uplift_message": uplift_message},
    )

    error_map: dict[int, tuple[int, str]] = {
        400: (400, f"Uplift rejected the request (invalid request/number): {uplift_message}"),
        401: (401, "Uplift API key is invalid or missing."),
        402: (402, "Uplift account has insufficient credits to place a call."),
        404: (404, f"Uplift resource not found (check UPLIFT_ASSISTANT_ID): {uplift_message}"),
        429: (429, f"Uplift rate or concurrency limit reached: {uplift_message}"),
        500: (502, f"Uplift infrastructure error: {uplift_message}"),
    }

    if status == 409:
        detail = f"Uplift conflict (number busy or duplicate call in flight): {uplift_message}"
        raise HTTPException(status_code=409, detail=detail)

    http_status, detail = error_map.get(status, (502, f"Unexpected Uplift error {status}: {uplift_message}"))
    raise HTTPException(status_code=http_status, detail=detail)


# ---------------------------------------------------------------------------
# ── P0-A CANONICAL: Outbound call dispatch ──────────────────────────────────
# ---------------------------------------------------------------------------

async def dispatch_call() -> dict[str, Any]:
    """
    Place a real outbound Urdu medication-reminder call to TEST_PHONE_NUMBER.

    P0-A canonical path:
      1. Validate UPLIFT_ASSISTANT_ID — 503 if absent.
      2. Validate TEST_PHONE_NUMBER   — 503 if absent.
      3. Generate Idempotency-Key.
      4. POST to Uplift /calls with the configured assistant ID.
      5. Return {"callId": str, "status": "dispatched"}.

    This function:
      - NEVER creates an assistant dynamically.
      - NEVER inspects or accepts a medication name.
      - NEVER writes to SQLite.
      - NEVER writes adherence data.
    """
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured. "
                "Run scripts/create_uplift_assistant.py first, then set the "
                "returned realtimeAssistantId as UPLIFT_ASSISTANT_ID in Replit Secrets."
            ),
        )

    if not settings.test_phone_number:
        raise HTTPException(
            status_code=503,
            detail=(
                "TEST_PHONE_NUMBER is not configured. "
                "Add your Pakistani test phone number to Replit Secrets as TEST_PHONE_NUMBER."
            ),
        )

    idempotency_key = str(uuid.uuid4())
    masked = _mask_phone(settings.test_phone_number)
    logger.info(
        "UPLIFT_CALL_REQUESTED",
        extra={
            "assistantId": settings.uplift_assistant_id,
            "to": masked,
            "idempotencyKey": idempotency_key,
        },
    )

    payload = {
        "assistantId": settings.uplift_assistant_id,
        "to": settings.test_phone_number,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{UPLIFT_BASE_URL}/calls",
            json=payload,
            headers={
                **_auth_headers(),
                "Idempotency-Key": idempotency_key,
            },
        )

    _raise_for_uplift_error(response)
    data = response.json()

    call_id = data.get("callId") or data.get("id") or data.get("sessionId") or "unknown"
    logger.info("UPLIFT_CALL_DISPATCHED", extra={"callId": call_id, "to": masked})

    return {"callId": call_id, "status": "dispatched"}


# ---------------------------------------------------------------------------
# ── P0-A CANONICAL: Call / session status ───────────────────────────────────
# ---------------------------------------------------------------------------

async def get_call_status(limit: int = 10) -> list[dict[str, Any]]:
    """
    Retrieve recent Uplift session states for the configured assistant.

    P0-A canonical path: queries Uplift directly; no SQLite merge.
    Raises 503 if UPLIFT_ASSISTANT_ID is not configured.
    """
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured. "
                "Complete the assistant bootstrap step before checking call status."
            ),
        )

    logger.info(
        "UPLIFT_CALL_STATUS_CHECKED",
        extra={"assistantId": settings.uplift_assistant_id, "limit": limit},
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{UPLIFT_BASE_URL}/realtime-assistants/{settings.uplift_assistant_id}/sessions",
            params={"limit": limit},
            headers=_auth_headers(),
        )

    _raise_for_uplift_error(response)
    data = response.json()
    raw_sessions: list[dict] = data if isinstance(data, list) else data.get("sessions", [])
    return [_normalise_session(s) for s in raw_sessions]


def _normalise_session(session: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise a raw Uplift session object to the canonical DAWA shape.

    Authoritative real Uplift response fields (Singapore endpoint):
      state        — lifecycle string: dispatched|dialing|ringing|answered|completed|failed
      sessionId    — session identifier
      ringingAt    — ISO timestamp when ringing started (null if not yet reached)
      connectedAt  — ISO timestamp when connected
      answeredAt   — ISO timestamp when patient answered
      endedAt      — ISO timestamp when call ended
      createdAt    — ISO timestamp when session was created
      connected    — bool
      durationSec  — integer seconds (present after end)
      toNumber     — destination phone (masked before returning)
      fromNumber   — caller ID (masked before returning)

    Boolean lifecycle flags are derived from `state` (primary) plus
    timestamp presence as a fallback for milestone booleans:
      ringing  = state=="ringing"  OR ringingAt is present
      answered = state=="answered" OR answeredAt is present

    callId is included only if it genuinely exists in the response;
    it is NOT manufactured from sessionId.
    """
    state = session.get("state") or ""

    # Mask phone numbers — full numbers must never leave the backend
    to_raw = session.get("toNumber") or ""
    from_raw = session.get("fromNumber") or ""

    return {
        "sessionId":     session.get("sessionId") or session.get("id"),
        "callId":        session.get("callId") or None,   # only if genuinely present
        "status":        state,
        "dispatched":    state == "dispatched",
        "dialing":       state == "dialing",
        "ringing":       state == "ringing" or bool(session.get("ringingAt")),
        "answered":      state == "answered" or bool(session.get("answeredAt")),
        "completed":     state == "completed",
        "failed":        state == "failed",
        "failureReason": session.get("failureReason"),
        "connected":     session.get("connected"),
        "startedAt":     session.get("createdAt"),
        "ringingAt":     session.get("ringingAt"),
        "answeredAt":    session.get("answeredAt"),
        "endedAt":       session.get("endedAt"),
        "durationSec":   session.get("durationSec"),
        "toNumber":      _mask_phone(to_raw) if to_raw else None,
        "fromNumber":    _mask_phone(from_raw) if from_raw else None,
    }


# ---------------------------------------------------------------------------
# ── FUTURE-PHASE HELPERS ─────────────────────────────────────────────────────
# These functions are NOT called by any P0-A code path.  They are preserved
# here for use by future phases (P0-B, P1, etc.) and for the bootstrap script.
# ---------------------------------------------------------------------------

def get_call_log() -> list[dict]:
    """Return persisted call log from SQLite, most-recent first. (Future-phase.)"""
    from app.services.call_store import get_all_calls  # lazy — not loaded in P0-A
    return get_all_calls(limit=50)


def _append_call_log(log_id: str, call_id: str, medication: str, phone_masked: str = "") -> None:
    """Append a call record to SQLite. (Future-phase.)"""
    from app.services.call_store import append_call  # lazy — not loaded in P0-A
    append_call(log_id=log_id, call_id=call_id, medication=medication, phone_masked=phone_masked)


def _build_instructions(medication_name: str) -> str:
    """
    Build medication-aware Urdu instructions for the Uplift realtime assistant.
    Used by the bootstrap script and future per-medication assistant creation.
    """
    return (
        "آپ DAWA کے ایک مددگار اسسٹنٹ ہیں جو مریضوں کو ادویات یاد دلاتے ہیں۔ "
        "صرف اردو میں بات کریں۔ "
        "پہلے مریض کو سلام کریں اور پوچھیں کہ وہ کیسے ہیں۔ "
        f"پھر پوچھیں: 'کیا آپ نے آج اپنی دوائی {medication_name} لی ہے؟' "
        "اگر مریض 'ہاں' کہیں تو خوشی سے تصدیق کریں اور کہیں 'بہت اچھا، شکریہ'۔ "
        "اگر مریض 'نہیں' کہیں تو صرف شکریہ کہیں اور تجویز کریں کہ وہ اپنے ڈاکٹر سے رابطہ کریں۔ "
        "صرف دوائی لینے کی تصدیق کریں — خوراک، ضمنی اثرات یا طبی معلومات پر بالکل بات نہ کریں۔ "
        "گفتگو مختصر اور قدرتی رکھیں۔ "
        "اندرونی تفصیلات ظاہر نہ کریں۔"
    )


async def create_assistant(
    name: str = "DAWA Urdu Medication Reminder",
    medication_name: str = "آپ کی دوائی",
) -> dict[str, Any]:
    """
    Create a new Uplift realtime assistant configured for Urdu outbound medication calls.

    Called once via scripts/create_uplift_assistant.py — not on server startup.
    Returns the full Uplift response dict (contains realtimeAssistantId).
    """
    logger.info("UPLIFT_ASSISTANT_CREATE_REQUEST", extra={"name": name})

    instructions = _build_instructions(medication_name)
    payload = {
        "name": name,
        "config": {
            "agent": {
                "instructions": instructions,
                "initialGreeting": True,
                "greetingInstructions": "السلام علیکم! میں DAWA کا ادویات یاد دہانی اسسٹنٹ ہوں۔",
            },
            "stt": {
                "default": {
                    "provider": "soniox",
                    "model": "stt-rt-v4",
                    "language": "ur",
                }
            },
            "tts": {
                "default": {
                    "provider": "upliftai",
                    "voiceId": "helpdesk-agent",
                    "outputFormat": "MP3_22050_32",
                }
            },
            "llm": {
                "default": {
                    "provider": "google",
                    "model": "gemini-2.5-flash",
                }
            },
        },
    }

    # Structural diagnostics — safe to log (no secrets)
    logger.info(
        "UPLIFT_ASSISTANT_PAYLOAD_SHAPE payload_type=%s config_type=%s config_keys=%s",
        type(payload).__name__,
        type(payload["config"]).__name__,
        sorted(payload["config"].keys()),
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{UPLIFT_BASE_URL}/realtime-assistants",
            json=payload,
            headers=_auth_headers(),
        )

    _raise_for_uplift_error(response)
    data = response.json()
    logger.info("UPLIFT_ASSISTANT_CREATED", extra={"assistantId": data.get("realtimeAssistantId")})
    return data


# Maps medication_name -> realtimeAssistantId (future-phase in-process cache).
_medication_assistant_cache: dict[str, str] = {}


async def get_or_create_medication_assistant(medication_name: str) -> str:
    """
    Return a cached Uplift assistant ID for *medication_name*, creating one on
    first use if not already cached.  (Future-phase — not called by P0-A dispatch_call.)
    """
    if medication_name in _medication_assistant_cache:
        cached_id = _medication_assistant_cache[medication_name]
        logger.debug(
            "MEDICATION_ASSISTANT_CACHE_HIT",
            extra={"medication": medication_name, "assistantId": cached_id},
        )
        return cached_id

    logger.info("MEDICATION_ASSISTANT_CREATE_START", extra={"medication": medication_name})
    data = await create_assistant(
        name=f"DAWA Urdu - {medication_name}",
        medication_name=medication_name,
    )
    assistant_id: str | None = data.get("realtimeAssistantId")
    if not assistant_id:
        raise HTTPException(
            status_code=502,
            detail="Uplift did not return a realtimeAssistantId for the new medication assistant.",
        )

    _medication_assistant_cache[medication_name] = assistant_id
    logger.info(
        "MEDICATION_ASSISTANT_CACHED",
        extra={"medication": medication_name, "assistantId": assistant_id},
    )
    return assistant_id


async def update_assistant_instructions(medication_name: str) -> None:
    """
    PATCH the base Uplift assistant's instructions to include a specific medication name.
    (Future-phase — not called by P0-A dispatch_call.)
    """
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured. "
                "Run scripts/create_uplift_assistant.py first."
            ),
        )

    payload = {"instructions": _build_instructions(medication_name)}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.patch(
            f"{UPLIFT_BASE_URL}/realtime-assistants/{settings.uplift_assistant_id}",
            json=payload,
            headers=_auth_headers(),
        )

    _raise_for_uplift_error(response)
    logger.info(
        "UPLIFT_ASSISTANT_UPDATED",
        extra={"assistantId": settings.uplift_assistant_id, "medication": medication_name},
    )
