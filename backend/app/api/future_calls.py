"""
DAWA Future-Phase Routes — NOT registered in the P0-A application.

This module contains all route handlers, helpers, and models that were built
beyond the P0-A scope. The router defined here is intentionally excluded from
app/main.py during P0-A.

To activate these routes in a later phase, add to main.py:
    from app.api.future_calls import router as future_router
    app.include_router(future_router)

Routes preserved here:
  GET  /api/call-log                — persistent SQLite call log (admin token required)
  POST /api/webhook/call-complete   — Uplift session-complete callback (HMAC-SHA256 verified)

Also preserved:
  - Admin token auth helper (_require_admin_token)
  - Webhook signature verification (_verify_webhook_signature)
  - Adherence outcome extraction (_extract_adherence_status and helpers)
  - CallRequest body model with medication_name validation
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.config import settings
from app.services.call_store import update_call_status
from app.services.uplift import get_call_log

logger = logging.getLogger("dawa.future")

# This router is defined but NOT included in app/main.py during P0-A.
router = APIRouter(prefix="/api")

_MEDICATION_MAX_LEN = 100
_MEDICATION_DISALLOWED = re.compile(r"[\x00-\x1f\x7f]")


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_admin_token(token: str | None) -> None:
    """Raise 403 if the provided token does not match DAWA_ADMIN_TOKEN."""
    if not settings.dawa_admin_token or token != settings.dawa_admin_token:
        raise HTTPException(status_code=403, detail="X-Admin-Token header is required.")


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class CallRequest(BaseModel):
    """
    Optional body for a future POST /api/test-call that accepts medication names.

    medication_name: name of the medicine to ask about in Urdu.
                     Defaults to a generic "your medicine" phrase if omitted.
    """
    medication_name: str = "آپ کی دوائی"  # "your medicine"

    @field_validator("medication_name")
    @classmethod
    def validate_medication_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("medication_name must not be empty.")
        if len(v) > _MEDICATION_MAX_LEN:
            raise ValueError(
                f"medication_name must be at most {_MEDICATION_MAX_LEN} characters "
                f"(got {len(v)})."
            )
        if _MEDICATION_DISALLOWED.search(v):
            raise ValueError(
                "medication_name must not contain newlines or control characters."
            )
        return v


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/call-log")
async def call_log(x_admin_token: str | None = Header(default=None)) -> list:
    """
    Return the persistent SQLite call log (most-recent first).

    Requires the X-Admin-Token header to match DAWA_ADMIN_TOKEN (Replit Secret).
    Returns 403 if the token is absent, unset, or incorrect.

    Each entry contains:
      logId        — unique ID assigned at dispatch time
      callId       — Uplift call ID (or "unknown" if Uplift did not return one)
      medication   — medication name passed at dispatch time
      dispatchedAt — ISO-8601 UTC timestamp
      status       — "dispatched" | "taken" | "not_taken" | "no_answer"
    """
    _require_admin_token(x_admin_token)
    return get_call_log()


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------

def _verify_webhook_signature(body: bytes, signature_header: str | None) -> None:
    """
    Verify the HMAC-SHA256 signature sent by Uplift on session-complete webhooks.

    Expected header format: "sha256=<hex_digest>"

    Behaviour:
    - UPLIFT_WEBHOOK_SECRET set     → always verify; 401 on mismatch or missing header.
    - UPLIFT_WEBHOOK_SECRET absent, DAWA_DEV_MODE=true  → skip with a warning (dev only).
    - UPLIFT_WEBHOOK_SECRET absent, DAWA_DEV_MODE=false → reject with 503 (fail closed).
    """
    if not settings.uplift_webhook_secret:
        if settings.dawa_dev_mode:
            logger.warning(
                "WEBHOOK_SIGNATURE_SKIP — UPLIFT_WEBHOOK_SECRET not set, "
                "skipping verification (DAWA_DEV_MODE=true)"
            )
            return
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_WEBHOOK_SECRET is not configured. "
                "Set it in Replit Secrets before accepting webhooks. "
                "To run without a secret in local development, set DAWA_DEV_MODE=true."
            ),
        )

    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Uplift-Signature header.")

    expected_prefix = "sha256="
    if signature_header.startswith(expected_prefix):
        provided_hex = signature_header[len(expected_prefix):]
    else:
        provided_hex = signature_header

    expected_hex = hmac.new(
        settings.uplift_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(provided_hex, expected_hex):
        logger.warning("WEBHOOK_SIGNATURE_MISMATCH")
        raise HTTPException(status_code=401, detail="Webhook signature verification failed.")


# ---------------------------------------------------------------------------
# Adherence outcome extraction
# ---------------------------------------------------------------------------

_TAKEN_KEYWORDS: frozenset[str] = frozenset({"ہاں", "haan", "ha", "yes", "ji", "جی"})
_NOT_TAKEN_KEYWORDS: frozenset[str] = frozenset({"نہیں", "nahin", "nahi", "no", "nay"})
_PATIENT_ROLES: frozenset[str] = frozenset({"user", "patient", "caller", "human", "customer"})


def _normalize_transcript_text(text: str) -> str:
    """Strip punctuation, collapse whitespace, and lowercase."""
    import re as _re
    stripped = _re.sub(r"[^\w\s]", " ", text, flags=_re.UNICODE)
    return stripped.lower()


def _extract_patient_text(transcript: list | str | None) -> str:
    """
    Return the patient's side of the conversation as a single plain-text string.

    For structured transcripts (list of turn dicts):
      - Only patient-role turns are included when ANY turn has role/speaker info.
      - Falls back to ALL turns only when NO turn has any attribution.
    For plain-text transcripts, the entire text is returned.
    """
    if not transcript:
        return ""

    if isinstance(transcript, list):
        patient_turns: list[str] = []
        unattributed_turns: list[str] = []
        has_any_attribution = False

        for turn in transcript:
            if not isinstance(turn, dict):
                continue
            role = (turn.get("role") or turn.get("speaker") or "").lower().strip()
            text = (turn.get("text") or turn.get("content") or turn.get("message") or "").strip()

            if role:
                has_any_attribution = True
                if role in _PATIENT_ROLES:
                    patient_turns.append(text)
            else:
                unattributed_turns.append(text)

        if has_any_attribution:
            return " ".join(patient_turns)
        return " ".join(unattributed_turns)

    return str(transcript)


def _find_last_keyword_position(normalized_tokens: list[str], keywords: frozenset[str]) -> int:
    """Return the index of the last token that matches any keyword, or -1 if none."""
    last = -1
    for i, token in enumerate(normalized_tokens):
        if token in keywords:
            last = i
    return last


def _extract_adherence_status(payload: dict) -> str:
    """
    Derive adherence status from an Uplift session-complete webhook payload.

    Priority order:
    1. Unanswered/failed call status → "no_answer".
    2. Explicit outcome/adherenceOutcome field → "taken" | "not_taken".
    3. Patient transcript keyword scan (punctuation-normalised, patient-turns-only).
       - If both yes and no keywords appear, the one occurring LAST wins.
    4. Default → "no_answer".
    """
    call_status = (payload.get("status") or "").lower()

    if call_status in {"no_answer", "unanswered", "failed", "missed", "busy"}:
        return "no_answer"

    outcome = payload.get("outcome") or payload.get("adherenceOutcome") or ""
    if outcome:
        outcome_lower = outcome.lower().strip()
        if outcome_lower in {"taken", "yes", "haan", "ہاں"}:
            return "taken"
        if outcome_lower in {"not_taken", "no", "nahin", "نہیں"}:
            return "not_taken"

    raw_transcript = payload.get("transcript") or payload.get("transcription") or ""
    patient_text = _extract_patient_text(raw_transcript)
    normalized = _normalize_transcript_text(patient_text)
    tokens = normalized.split()

    taken_pos = _find_last_keyword_position(tokens, _TAKEN_KEYWORDS)
    not_taken_pos = _find_last_keyword_position(tokens, _NOT_TAKEN_KEYWORDS)

    if taken_pos == -1 and not_taken_pos == -1:
        return "no_answer"
    if taken_pos >= not_taken_pos:
        return "taken"
    return "not_taken"


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@router.post("/webhook/call-complete", status_code=200)
async def webhook_call_complete(
    request: Request,
    x_uplift_signature: str | None = Header(default=None),
) -> dict:
    """
    Receive an Uplift session-complete webhook and update the call log status.

    1. Verifies the HMAC-SHA256 signature (X-Uplift-Signature header).
    2. Extracts the patient's adherence response from the payload.
    3. Updates the call log entry with the derived status.

    NOTE: The Uplift webhook feature is UNVERIFIED against the official Uplift
    Hackathon Guide at time of writing. Do not rely on this endpoint in P0-A.
    """
    body = await request.body()
    _verify_webhook_signature(body, x_uplift_signature)

    try:
        payload: dict = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON.")

    call_id: str | None = payload.get("callId") or payload.get("sessionId") or payload.get("id")
    if not call_id:
        logger.warning("WEBHOOK_MISSING_CALL_ID", extra={"payload_keys": list(payload.keys())})
        raise HTTPException(status_code=400, detail="Webhook payload must include 'callId'.")

    adherence_status = _extract_adherence_status(payload)
    update_call_status(call_id=call_id, status=adherence_status)

    logger.info(
        "WEBHOOK_CALL_COMPLETE",
        extra={"callId": call_id, "adherenceStatus": adherence_status},
    )

    return {"received": True, "callId": call_id, "status": adherence_status}
