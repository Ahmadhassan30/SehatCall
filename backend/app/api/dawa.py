"""
DAWA P1 API routes.

GET  /api/dawa/demo          — seeded patient + medications + recent dose events
POST /api/dawa/vmr/resolve   — deterministic medication identity resolution
POST /api/dawa/demo-call     — build verified context and dispatch Uplift call
GET  /api/dawa/call-status   — recent dose events with telephony lifecycle

P0-A routes (POST /api/test-call, GET /api/test-call/status) are unchanged.
"""

from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import UPLIFT_BASE_URL, settings
from app.services import dawa_store
from app.services.call_context import build_call_context
from app.services.vmr import resolve as vmr_resolve

logger = logging.getLogger("dawa.p1")

router = APIRouter(prefix="/api/dawa")


# ---------------------------------------------------------------------------
# GET /api/dawa/demo
# ---------------------------------------------------------------------------

@router.get("/demo")
async def get_demo() -> dict:
    """
    Return the seeded demo patient, her medications, and her recent dose events.
    Used by the caregiver app to populate the dashboard on load.
    """
    patient = dawa_store.get_patient("razia-bibi")
    if not patient:
        raise HTTPException(status_code=503, detail="Demo data not seeded. Restart the server.")

    medications = dawa_store.get_medications_for_patient("razia-bibi")
    # Enrich each medication with its verified cues
    for med in medications:
        med["cues"] = dawa_store.get_medication_cues(med["id"])

    dose_events = dawa_store.get_recent_dose_events(patient_id="razia-bibi", limit=5)

    return {
        "patient": patient,
        "medications": medications,
        "doseEvents": dose_events,
    }


# ---------------------------------------------------------------------------
# POST /api/dawa/vmr/resolve
# ---------------------------------------------------------------------------

class VMRRequest(BaseModel):
    patientId: str
    cues: dict[str, str]


@router.post("/vmr/resolve")
async def vmr_resolve_endpoint(body: VMRRequest) -> dict:
    """
    Deterministic medication identity resolution.

    Compares caller-supplied visual cues against caregiver-verified cues.
    Returns UNIQUE | AMBIGUOUS | NO_MATCH — never a probability or guess.
    """
    patient = dawa_store.get_patient(body.patientId)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient not found: {body.patientId!r}")

    if not body.cues:
        raise HTTPException(status_code=400, detail="At least one cue is required.")

    result = vmr_resolve(body.patientId, body.cues)
    return result.to_dict()


# ---------------------------------------------------------------------------
# POST /api/dawa/demo-call
# ---------------------------------------------------------------------------

class DemoCallRequest(BaseModel):
    patientId: str
    medicationId: str
    # NOTE: destination phone number is NEVER accepted from the request.
    # It always comes from TEST_PHONE_NUMBER (Replit Secret).


@router.post("/demo-call")
async def demo_call(body: DemoCallRequest) -> dict:
    """
    Build a verified call context and dispatch a real Uplift outbound call.

    - patientId must resolve to an existing patient.
    - medicationId must belong to that patient.
    - Destination phone always comes from TEST_PHONE_NUMBER (never from request).
    - assistantId always comes from UPLIFT_ASSISTANT_ID (never from request).
    - Passes variables and additionalInstructions to Uplift per hackathon guide.
    - Creates a dose_event record (scheduled → calling).
    - Returns {callId, status, doseEventId}.
    """
    # Validate patient
    patient = dawa_store.get_patient(body.patientId)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient not found: {body.patientId!r}")

    # Validate medication belongs to patient
    medication = dawa_store.get_medication(body.medicationId)
    if not medication or medication["patient_id"] != body.patientId:
        raise HTTPException(
            status_code=404,
            detail=f"Medication {body.medicationId!r} not found for patient {body.patientId!r}",
        )

    # Validate required server-side secrets
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured. "
                "Run scripts/create_uplift_assistant.py first."
            ),
        )
    if not settings.test_phone_number:
        raise HTTPException(
            status_code=503,
            detail=(
                "TEST_PHONE_NUMBER is not configured. "
                "Set it in Replit Secrets."
            ),
        )

    # Build verified call context from database
    try:
        ctx = build_call_context(body.patientId, body.medicationId)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Create dose event (scheduled → calling)
    dose_event = dawa_store.create_dose_event(
        patient_id=body.patientId,
        medication_id=body.medicationId,
        scheduled_time=medication["schedule_time"],
        call_status="calling",
    )

    # Dispatch to Uplift
    idempotency_key = str(uuid.uuid4())
    payload: dict = {
        "assistantId": settings.uplift_assistant_id,
        "to": settings.test_phone_number,
        "variables": ctx.variables,
        "additionalInstructions": ctx.additional_instructions,
    }

    logger.info(
        "DAWA_CALL_DISPATCH",
        extra={
            "patientId": body.patientId,
            "medicationId": body.medicationId,
            "doseEventId": dose_event["id"],
            "idempotencyKey": idempotency_key,
        },
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{UPLIFT_BASE_URL}/calls",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.upliftai_api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
        )

    if not response.is_success:
        # Update dose event to failed
        dawa_store.update_dose_event(dose_event["id"], call_status="failed")
        try:
            uplift_msg = response.json().get("message") or response.text
        except Exception:
            uplift_msg = response.text
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Uplift rejected call request: {uplift_msg}",
        )

    data = response.json()
    call_id = data.get("callId") or data.get("id") or data.get("sessionId") or "unknown"

    # Update dose event with Uplift call ID
    dawa_store.update_dose_event(dose_event["id"], call_id=call_id, call_status="dispatched")

    logger.info(
        "DAWA_CALL_DISPATCHED",
        extra={"callId": call_id, "doseEventId": dose_event["id"]},
    )

    return {
        "callId": call_id,
        "status": "dispatched",
        "doseEventId": dose_event["id"],
    }


# ---------------------------------------------------------------------------
# GET /api/dawa/call-status
# ---------------------------------------------------------------------------

@router.get("/call-status")
async def call_status(limit: int = 10) -> dict:
    """
    Return recent dose events merged with live Uplift session status.

    Uplift session data is fetched only when UPLIFT_ASSISTANT_ID is configured.
    Falls back to stored dose_event call_status when Uplift is unavailable.

    Adherence outcome is DISTINCT from telephony status.
    A completed call does NOT imply the medication was taken.
    """
    dose_events = dawa_store.get_recent_dose_events(patient_id="razia-bibi", limit=limit)

    # Attempt to fetch live session states from Uplift
    live_sessions: dict[str, dict] = {}
    if settings.uplift_assistant_id:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{UPLIFT_BASE_URL}/realtime-assistants/{settings.uplift_assistant_id}/sessions",
                    params={"limit": limit},
                    headers={
                        "Authorization": f"Bearer {settings.upliftai_api_key}",
                    },
                )
            if resp.is_success:
                data = resp.json()
                sessions: list[dict] = data if isinstance(data, list) else data.get("sessions", [])
                for s in sessions:
                    cid = s.get("callId") or s.get("id")
                    if cid:
                        live_sessions[cid] = s
        except Exception as exc:
            logger.warning("UPLIFT_STATUS_FETCH_FAILED", extra={"error": str(exc)})

    # Merge live session data into dose events
    enriched: list[dict] = []
    for event in dose_events:
        call_id = event.get("callId")
        merged = dict(event)
        if call_id and call_id in live_sessions:
            s = live_sessions[call_id]
            merged["liveStatus"] = {
                "status":        s.get("status"),
                "dispatched":    s.get("dispatched"),
                "dialing":       s.get("dialing"),
                "ringing":       s.get("ringing"),
                "answered":      s.get("answered"),
                "completed":     s.get("completed"),
                "failed":        s.get("failed"),
                "failureReason": s.get("failureReason"),
                "startedAt":     s.get("startedAt") or s.get("createdAt"),
                "endedAt":       s.get("endedAt"),
            }
            # Update stored call_status to match live data (best-effort)
            live_call_status = _derive_call_status(s)
            if live_call_status:
                merged["callStatus"] = live_call_status
        else:
            merged["liveStatus"] = None
        enriched.append(merged)

    return {
        "doseEvents": enriched,
        # Explicitly note: completing a call does NOT mean medication was taken
        "_note": "adherenceOutcome is distinct from callStatus. A completed call does not imply TAKEN.",
    }


def _derive_call_status(session: dict) -> str | None:
    """Map Uplift boolean session flags to a call status string."""
    if session.get("failed"):
        return "failed"
    if session.get("completed"):
        return "completed"
    if session.get("answered"):
        return "answered"
    if session.get("ringing"):
        return "ringing"
    if session.get("dialing"):
        return "dialing"
    if session.get("dispatched"):
        return "dispatched"
    status = (session.get("status") or "").lower()
    if status in {"completed", "failed", "answered", "ringing", "dialing", "dispatched"}:
        return status
    return None
