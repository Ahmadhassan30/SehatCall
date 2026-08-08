"""
Uplift AI service layer for DAWA P0-B.

All HTTP communication with the Uplift API is centralised here.
No raw Uplift calls should appear in route handlers.

Singapore endpoint (ap-southeast-1) is used exclusively — this is the only
region that supports outbound calls to Pakistani phone numbers.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import UPLIFT_BASE_URL, settings
from app.services.call_store import append_call, get_all_calls

logger = logging.getLogger("dawa.uplift")


def get_call_log() -> list[dict]:
    """Return persisted call log from SQLite, most-recent first."""
    return get_all_calls(limit=50)


def _append_call_log(log_id: str, call_id: str, medication: str, phone_masked: str = "") -> None:
    append_call(log_id=log_id, call_id=call_id, medication=medication, phone_masked=phone_masked)


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
        # 409 can mean either "number busy" or "duplicate in-flight call"
        detail = f"Uplift conflict (number busy or duplicate call in flight): {uplift_message}"
        raise HTTPException(status_code=409, detail=detail)

    http_status, detail = error_map.get(status, (502, f"Unexpected Uplift error {status}: {uplift_message}"))
    raise HTTPException(status_code=http_status, detail=detail)


# ---------------------------------------------------------------------------
# Assistant instructions builder
# ---------------------------------------------------------------------------

def _build_instructions(medication_name: str) -> str:
    """
    Build medication-aware Urdu instructions for the Uplift realtime assistant.

    The assistant will:
    - Greet the patient warmly in Urdu
    - Ask specifically whether they took the named medication today
    - Confirm their response ("haan" = yes / "nahin" = no)
    - Thank them and end the call
    - NEVER give medical advice or discuss dosage
    """
    return (
        "آپ DAWA کے ایک مددگار اسسٹنٹ ہیں جو مریضوں کو ادویات یاد دلاتے ہیں۔ "
        # You are a DAWA assistant that reminds patients about their medicines.
        "صرف اردو میں بات کریں۔ "
        # Speak only in Urdu.
        "پہلے مریض کو سلام کریں اور پوچھیں کہ وہ کیسے ہیں۔ "
        # First greet the patient and ask how they are.
        f"پھر پوچھیں: 'کیا آپ نے آج اپنی دوائی {medication_name} لی ہے؟' "
        # Then ask: 'Did you take your medicine [medication_name] today?'
        "اگر مریض 'ہاں' کہیں تو خوشی سے تصدیق کریں اور کہیں 'بہت اچھا، شکریہ'۔ "
        # If patient says 'haan' (yes), confirm warmly: 'Very good, thank you.'
        "اگر مریض 'نہیں' کہیں تو صرف شکریہ کہیں اور تجویز کریں کہ وہ اپنے ڈاکٹر سے رابطہ کریں۔ "
        # If patient says 'nahin' (no), only thank them and suggest they contact their doctor — never tell them to take the medicine.
        "صرف دوائی لینے کی تصدیق کریں — خوراک، ضمنی اثرات یا طبی معلومات پر بالکل بات نہ کریں۔ "
        # Only confirm adherence — never discuss dose, side effects, or medical information.
        "گفتگو مختصر اور قدرتی رکھیں۔ "
        # Keep the conversation brief and natural.
        "اندرونی تفصیلات ظاہر نہ کریں۔"
        # Do NOT reveal internal implementation details.
    )


# ---------------------------------------------------------------------------
# Assistant creation
# ---------------------------------------------------------------------------

async def create_assistant(
    name: str = "DAWA Urdu Medication Reminder",
    medication_name: str = "آپ کی دوائی",  # default: "your medicine"
) -> dict[str, Any]:
    """
    Create a new Uplift realtime assistant configured for Urdu outbound medication calls.

    This is intended to be called once via the bootstrap script, not on server startup.

    Returns the full Uplift response dict (contains realtimeAssistantId).
    """
    logger.info("UPLIFT_ASSISTANT_CREATE_REQUEST", extra={"name": name})

    payload = {
        "name": name,
        "stt": {
            "provider": "soniox",
            "model": "stt-rt-v4",
            "language": "ur",
        },
        "tts": {
            "provider": "upliftai",
            "voiceId": "helpdesk-agent",
            "outputFormat": "MP3_22050_32",
        },
        "llm": {
            "provider": "google",
            "model": "gemini-2.5-flash",
        },
        "initialGreeting": True,
        "instructions": _build_instructions(medication_name),
    }

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


# ---------------------------------------------------------------------------
# Assistant instructions update (per-call medication injection)
# ---------------------------------------------------------------------------

async def update_assistant_instructions(medication_name: str) -> None:
    """
    PATCH the existing Uplift assistant's instructions to include the specific
    medication name for the upcoming call.

    Called automatically by dispatch_call() — not intended for direct use.
    """
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured. "
                "Run scripts/create_uplift_assistant.py first."
            ),
        )

    logger.info(
        "UPLIFT_ASSISTANT_UPDATE_REQUEST",
        extra={"assistantId": settings.uplift_assistant_id, "medication": medication_name},
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


# ---------------------------------------------------------------------------
# Outbound call dispatch
# ---------------------------------------------------------------------------

async def dispatch_call(medication_name: str = "آپ کی دوائی") -> dict[str, Any]:
    """
    Place a real outbound Urdu medication-reminder call to TEST_PHONE_NUMBER.

    Steps:
    1. Validate required secrets (UPLIFT_ASSISTANT_ID, TEST_PHONE_NUMBER).
    2. PATCH the assistant instructions to embed the specific medication name.
    3. Dispatch the call via Uplift.
    4. Append an entry to the in-memory call log.

    Returns a safe dict: {"callId": str, "status": "dispatched", "medication": str, "logId": str}.
    NOTE: "dispatched" means the request was accepted and dialling was initiated.
          It does NOT mean the call was answered or that a conversation occurred.
    """
    # Validate call-time required secrets
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured. "
                "Run scripts/create_uplift_assistant.py first, then add the returned ID "
                "to Replit Secrets as UPLIFT_ASSISTANT_ID and restart the workflow."
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

    # Inject medication name into assistant instructions before calling
    await update_assistant_instructions(medication_name)

    idempotency_key = str(uuid.uuid4())
    log_id = str(uuid.uuid4())
    masked = _mask_phone(settings.test_phone_number)
    logger.info(
        "UPLIFT_CALL_REQUESTED",
        extra={
            "assistantId": settings.uplift_assistant_id,
            "to": masked,
            "medication": medication_name,
            "idempotencyKey": idempotency_key,
        },
    )

    payload = {
        "assistantId": settings.uplift_assistant_id,
        "to": settings.test_phone_number,
        "metadata": {
            "dawa_log_id": log_id,
            "medication": medication_name,
        },
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
    logger.info(
        "UPLIFT_CALL_DISPATCHED",
        extra={"callId": call_id, "to": masked, "medication": medication_name},
    )

    # Record in persistent call log
    _append_call_log(log_id=log_id, call_id=call_id, medication=medication_name, phone_masked=masked)

    # Only return safe, non-secret information
    return {
        "callId": call_id,
        "status": "dispatched",
        "medication": medication_name,
        "logId": log_id,
    }


# ---------------------------------------------------------------------------
# Call / session status
# ---------------------------------------------------------------------------

async def get_call_status(limit: int = 10) -> list[dict[str, Any]]:
    """
    Retrieve recent Uplift session states for the configured assistant,
    merged with locally persisted call records so history survives restarts.

    - Live Uplift sessions take precedence for calls Uplift still knows about.
    - Locally persisted records fill in any calls that have aged out of Uplift's
      session history window.

    Returns a normalised list of compact session summaries, most-recent first.
    The caller is responsible for polling at a polite cadence (2–5 seconds).
    """
    from app.services.call_store import get_all_calls as _local_calls

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

    # Fetch live sessions from Uplift
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{UPLIFT_BASE_URL}/realtime-assistants/{settings.uplift_assistant_id}/sessions",
                params={"limit": limit},
                headers=_auth_headers(),
            )
        _raise_for_uplift_error(response)
        data = response.json()
        raw_sessions: list[dict] = data if isinstance(data, list) else data.get("sessions", [])
        live_sessions = [_normalise_session(s) for s in raw_sessions]
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("UPLIFT_STATUS_FETCH_FAILED", extra={"error": str(exc)})
        live_sessions = []

    # Build a set of callIds Uplift returned so we can avoid duplicates
    live_call_ids: set[str] = {
        s["callId"] for s in live_sessions if s.get("callId")
    }
    live_session_ids: set[str] = {
        s["sessionId"] for s in live_sessions if s.get("sessionId")
    }

    # Pull persisted local records; exclude any that are already in the live response
    local_records = _local_calls(limit=limit)
    merged: list[dict[str, Any]] = list(live_sessions)
    for record in local_records:
        call_id = record.get("callId")
        if call_id and call_id in live_call_ids:
            continue  # already represented by a live entry
        if call_id and call_id in live_session_ids:
            continue
        # Emit a minimal status-compatible entry from the local record.
        # Sensitive fields (medication, phoneMasked) are intentionally omitted
        # because this endpoint is unauthenticated — full details are available
        # only via the admin-protected GET /api/call-log endpoint.
        merged.append(
            {
                "sessionId": record["logId"],
                "callId": record["callId"],
                "status": record["status"],
                "dispatched": record["dispatchedAt"],
                "dialing": None,
                "ringing": None,
                "answered": None,
                "completed": None,
                "failed": None,
                "failureReason": None,
                "startedAt": record["dispatchedAt"],
                "endedAt": None,
                "source": "local",
            }
        )

    # Return up to `limit` entries (live ones first, they're already ordered)
    return merged[:limit]


def _normalise_session(session: dict[str, Any]) -> dict[str, Any]:
    """Extract the fields relevant to P0-B status inspection."""
    return {
        "sessionId": session.get("sessionId") or session.get("id"),
        "callId": session.get("callId"),
        "status": session.get("status"),
        "dispatched": session.get("dispatched"),
        "dialing": session.get("dialing"),
        "ringing": session.get("ringing"),
        "answered": session.get("answered"),
        "completed": session.get("completed"),
        "failed": session.get("failed"),
        "failureReason": session.get("failureReason"),
        "startedAt": session.get("startedAt") or session.get("createdAt"),
        "endedAt": session.get("endedAt"),
    }
