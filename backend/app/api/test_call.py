"""
DAWA P0-A — Test call API routes.

POST /api/test-call        — dispatch a real outbound Urdu medication-reminder call
GET  /api/test-call/status — inspect recent Uplift session states

No authentication required.
No request body required.
Phone number and assistant ID are always read from server-side configuration.

Future-phase routes (GET /api/call-log, POST /api/webhook/call-complete) live in
app/api/future_calls.py and are intentionally NOT registered in the application
during P0-A.

The canonical P0-A router imports only:
  - app.services.uplift.dispatch_call
  - app.services.uplift.get_call_status
It does NOT import call_store, webhook logic, adherence parsing, admin auth,
or medication-specific models.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.uplift import dispatch_call, get_call_status

router = APIRouter(prefix="/api")


@router.post("/test-call")
async def trigger_test_call() -> dict:
    """
    Dispatch a real outbound Urdu medication-reminder call to the configured TEST_PHONE_NUMBER.

    No request body required.
    Reads phone number and assistant ID from server-side environment only.
    Returns {"callId": "...", "status": "dispatched"} on success.
    Raises 503 if UPLIFT_ASSISTANT_ID or TEST_PHONE_NUMBER are not yet configured.
    """
    return await dispatch_call()


@router.get("/test-call/status")
async def test_call_status(limit: int = 10) -> list:
    """
    Return recent Uplift session states for the configured assistant.

    Intended polling cadence: every 2–5 seconds from a client.
    This endpoint does NOT poll Uplift continuously — it fetches once per request.
    Raises 503 if UPLIFT_ASSISTANT_ID is not configured.
    """
    return await get_call_status(limit=limit)
