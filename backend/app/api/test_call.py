"""
Test call API routes for DAWA P0-B.

POST /api/test-call        — dispatch a real outbound Urdu medication-reminder call (admin token required)
GET  /api/test-call/status — inspect recent Uplift session states
GET  /api/call-log         — inspect the in-memory call log (admin token required)

The phone number and assistant ID are always read from server-side configuration.
They are NEVER accepted from the request body.
A real outbound call only happens when the developer deliberately POSTs to /api/test-call
with the correct X-Admin-Token header.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator

from app.config import settings
from app.services.uplift import dispatch_call, get_call_log, get_call_status

router = APIRouter(prefix="/api")

# Max allowed length for medication names — prevents oversized prompt injection
_MEDICATION_MAX_LEN = 100
# Block newlines and any ASCII control characters that could break the prompt
_MEDICATION_DISALLOWED = re.compile(r"[\x00-\x1f\x7f]")


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_admin_token(token: str | None) -> None:
    """Raise 403 if the provided token does not match DAWA_ADMIN_TOKEN."""
    if not settings.dawa_admin_token or token != settings.dawa_admin_token:
        raise HTTPException(status_code=403, detail="X-Admin-Token header is required.")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CallRequest(BaseModel):
    """
    Optional body for POST /api/test-call.

    medication_name: name of the medicine to ask about in Urdu.
                     Defaults to a generic "your medicine" phrase if omitted.
                     Max 100 characters; control characters are rejected.
    """
    medication_name: str = "آپ کی دوائی"  # "your medicine" — safe default

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

@router.post("/test-call")
async def trigger_test_call(
    body: CallRequest = CallRequest(),
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """
    Dispatch a real outbound Urdu medication-reminder call to the configured TEST_PHONE_NUMBER.

    Requires the X-Admin-Token header to match DAWA_ADMIN_TOKEN (Replit Secret).
    Returns 403 if the token is absent, unset, or incorrect.

    - Reads phone number and assistant ID from server-side environment only.
    - Updates the assistant's Urdu instructions to reference the specified medication.
    - Returns {"callId": "...", "status": "dispatched", "medication": "...", "logId": "..."} on success.
    - "dispatched" means Uplift accepted the request and began dialling.
      It does NOT mean the call was answered or that a conversation occurred.
    - Raises 503 with a clear message if UPLIFT_ASSISTANT_ID or TEST_PHONE_NUMBER
      are not yet configured.

    Example body:
        {"medication_name": "میٹفارمن"}
    """
    _require_admin_token(x_admin_token)
    return await dispatch_call(medication_name=body.medication_name)


@router.get("/test-call/status")
async def test_call_status(limit: int = 10) -> list:
    """
    Return recent Uplift session states for the configured assistant.

    Intended polling cadence: every 2–5 seconds from a client.
    This endpoint does NOT poll Uplift continuously — it fetches once per request.

    Raises 503 if UPLIFT_ASSISTANT_ID is not configured.
    """
    return await get_call_status(limit=limit)


@router.get("/call-log")
async def call_log(x_admin_token: str | None = Header(default=None)) -> list:
    """
    Return the in-memory call log (most-recent first).

    Requires the X-Admin-Token header to match DAWA_ADMIN_TOKEN (Replit Secret).
    Returns 403 if the token is absent, unset, or incorrect.

    Each entry contains:
      logId        — unique ID assigned at dispatch time
      callId       — Uplift call ID (or "unknown" if Uplift did not return one)
      medication   — medication name passed at dispatch time
      dispatchedAt — ISO-8601 UTC timestamp
      status       — always "dispatched" in P0-B (no webhook yet)

    Note: this log is cleared on server restart. Persistent storage is out of scope for P0-B.
    """
    _require_admin_token(x_admin_token)
    return get_call_log()
