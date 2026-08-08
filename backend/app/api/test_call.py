"""
Test call API routes for DAWA P0-A.

POST /api/test-call       — dispatch a real outbound Urdu call
GET  /api/test-call/status — inspect recent Uplift session states

The phone number and assistant ID are always read from server-side configuration.
They are NEVER accepted from the request body.
A real outbound call only happens when the developer deliberately POSTs to /api/test-call.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.uplift import dispatch_call, get_call_status

router = APIRouter(prefix="/api")


@router.post("/test-call")
async def trigger_test_call() -> dict:
    """
    Dispatch a real outbound Urdu call to the configured TEST_PHONE_NUMBER.

    - Reads phone number and assistant ID from server-side environment only.
    - Returns {"callId": "...", "status": "dispatched"} on success.
    - "dispatched" means Uplift accepted the request and began dialling.
      It does NOT mean the call was answered or that a conversation occurred.
    - Raises 503 with a clear message if UPLIFT_ASSISTANT_ID or TEST_PHONE_NUMBER
      are not yet configured.
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
