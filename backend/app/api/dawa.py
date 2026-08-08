"""
DAWA P1+P2 API routes.

P1 routes (unchanged contract):
  GET  /api/dawa/demo              — seeded patient + medications + dose events
  POST /api/dawa/vmr/resolve       — deterministic medication identity resolution
  POST /api/dawa/demo-call         — manual call dispatch (reuses shared dispatch path)
  GET  /api/dawa/call-status       — recent dose events with live telephony status

P2 routes (new):
  POST /api/dawa/schedule-demo-call — schedule a call for 15–300 s from now
  POST /api/dawa/demo/reset         — clear demo dose events + queued scheduler jobs
  (GET /api/dawa/demo extended with scheduler state)

P0-A routes (POST /api/test-call, GET /api/test-call/status) are unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import UPLIFT_BASE_URL, settings
from app.services import dawa_store
from app.services import scheduler as sched
from app.services.call_context import build_call_context
from app.services.vmr import resolve as vmr_resolve

logger = logging.getLogger("dawa.api")

router = APIRouter(prefix="/api/dawa")

KARACHI_TZ = ZoneInfo("Asia/Karachi")

# ---------------------------------------------------------------------------
# GET /api/dawa/demo  (P1 + P2 extended)
# ---------------------------------------------------------------------------

@router.get("/demo")
async def get_demo() -> dict:
    """
    Return the seeded demo patient, her medications, recent dose events,
    and P2 scheduler state (server time, next scheduled call, pending jobs).
    """
    patient = dawa_store.get_patient("razia-bibi")
    if not patient:
        raise HTTPException(status_code=503, detail="Demo data not seeded. Restart the server.")

    medications = dawa_store.get_medications_for_patient("razia-bibi")
    for med in medications:
        med["cues"] = dawa_store.get_medication_cues(med["id"])

    dose_events = dawa_store.get_recent_dose_events(patient_id="razia-bibi", limit=10)

    # P2: scheduler state
    now_karachi = datetime.now(KARACHI_TZ)
    pending_jobs = sched.get_pending_job_info()
    pending_events = dawa_store.get_pending_dose_events()

    next_scheduled: dict | None = None
    if pending_events:
        ev = pending_events[0]
        try:
            fire_at_str = ev["scheduledTime"]
            fire_at = datetime.fromisoformat(fire_at_str)
            delay_remaining = max(0, int((fire_at - now_karachi).total_seconds()))
        except Exception:
            delay_remaining = None
        next_scheduled = {
            "doseEventId":  ev["id"],
            "medicationId": ev["medicationId"],
            "scheduledTime": ev["scheduledTime"],
            "callStatus":    ev["callStatus"],
            "delayRemainingSeconds": delay_remaining,
        }

    return {
        "patient": patient,
        "medications": medications,
        "doseEvents": dose_events,
        # P2 additions
        "serverTimeKarachi": now_karachi.isoformat(),
        "nextScheduledCall": next_scheduled,
        "pendingJobCount": len(pending_jobs),
        "pendingJobs": pending_jobs,
    }


# ---------------------------------------------------------------------------
# POST /api/dawa/vmr/resolve  (P1 unchanged)
# ---------------------------------------------------------------------------

class VMRRequest(BaseModel):
    patientId: str
    cues: dict[str, str]


@router.post("/vmr/resolve")
async def vmr_resolve_endpoint(body: VMRRequest) -> dict:
    """Deterministic medication identity resolution — no LLM, no probabilities."""
    patient = dawa_store.get_patient(body.patientId)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient not found: {body.patientId!r}")
    if not body.cues:
        raise HTTPException(status_code=400, detail="At least one cue is required.")
    result = vmr_resolve(body.patientId, body.cues)
    return result.to_dict()


# ---------------------------------------------------------------------------
# POST /api/dawa/demo-call  (P1 — now delegates to shared dispatch path)
# ---------------------------------------------------------------------------

class DemoCallRequest(BaseModel):
    patientId: str
    medicationId: str
    # Phone is NEVER accepted from request — always from TEST_PHONE_NUMBER


@router.post("/demo-call")
async def demo_call(body: DemoCallRequest) -> dict:
    """
    Manual call dispatch.  Reuses the same verified-context + Uplift path
    as the scheduler (sched.dispatch_call_via_uplift).
    """
    patient = dawa_store.get_patient(body.patientId)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient not found: {body.patientId!r}")

    medication = dawa_store.get_medication(body.medicationId)
    if not medication or medication["patient_id"] != body.patientId:
        raise HTTPException(
            status_code=404,
            detail=f"Medication {body.medicationId!r} not found for patient {body.patientId!r}",
        )

    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail="UPLIFT_ASSISTANT_ID not set. Run scripts/create_uplift_assistant.py first.",
        )
    if not settings.test_phone_number:
        raise HTTPException(
            status_code=503,
            detail="TEST_PHONE_NUMBER not set in Replit Secrets.",
        )

    # ── Active-call guard (same DB check as the scheduler) ───────────────
    # Prevents a second Uplift call while one is already in a non-terminal state
    # (dispatched / dialing / ringing / answered).
    if sched.has_active_call():
        raise HTTPException(
            status_code=409,
            detail="Another DAWA call is currently active",
        )

    # Create a dose event for this manual dispatch
    dose_event = dawa_store.create_dose_event(
        patient_id=body.patientId,
        medication_id=body.medicationId,
        scheduled_time=datetime.now(KARACHI_TZ).isoformat(),
        call_status="calling",
    )

    # ── Single authoritative dispatch path ────────────────────────────────
    try:
        call_id = await sched.dispatch_call_via_uplift(dose_event, retry_count=0)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("DAWA_CALL_DISPATCHED manual callId=%s event=%s", call_id, dose_event["id"])

    return {
        "callId": call_id,
        "status": "dispatched",
        "doseEventId": dose_event["id"],
    }


# ---------------------------------------------------------------------------
# GET /api/dawa/call-status  (P1 unchanged)
# ---------------------------------------------------------------------------

@router.get("/call-status")
async def call_status(limit: int = 10) -> dict:
    """
    Recent dose events merged with live Uplift telephony status.
    Completed call ≠ TAKEN — adherence_outcome remains null.
    """
    dose_events = dawa_store.get_recent_dose_events(patient_id="razia-bibi", limit=limit)

    live_sessions: dict[str, dict] = {}
    if settings.uplift_assistant_id:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{UPLIFT_BASE_URL}/realtime-assistants/{settings.uplift_assistant_id}/sessions",
                    params={"limit": limit},
                    headers={"Authorization": f"Bearer {settings.upliftai_api_key}"},
                )
            if resp.is_success:
                data = resp.json()
                sessions: list[dict] = data if isinstance(data, list) else data.get("sessions", [])
                for s in sessions:
                    cid = s.get("callId") or s.get("id")
                    if cid:
                        live_sessions[cid] = s
        except Exception as exc:
            logger.warning("UPLIFT_STATUS_FETCH_FAILED: %s", exc)

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
        else:
            merged["liveStatus"] = None
        enriched.append(merged)

    return {
        "doseEvents": enriched,
        "_note": "adherenceOutcome is distinct from callStatus. completed ≠ TAKEN.",
    }


# ---------------------------------------------------------------------------
# POST /api/dawa/schedule-demo-call  (P2 NEW)
# ---------------------------------------------------------------------------

class ScheduleDemoCallRequest(BaseModel):
    patientId: str
    medicationId: str
    delaySeconds: int = Field(default=60, ge=15, le=300)
    # phone / assistantId are intentionally NOT accepted from request body


@router.post("/schedule-demo-call")
async def schedule_demo_call(body: ScheduleDemoCallRequest) -> dict:
    """
    Schedule a one-shot call to fire in delaySeconds (15–300 s).
    Destination is always TEST_PHONE_NUMBER; assistant is UPLIFT_ASSISTANT_ID.
    Neither can be supplied by the caller.

    Creates a real dose_event; the APScheduler fires dispatch_call_via_uplift
    after the delay.  This enables the demo story:
      "I'll schedule Razia's reminder for one minute from now…"
      (phone rings without touching the app)
    """
    patient = dawa_store.get_patient(body.patientId)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient not found: {body.patientId!r}")

    medication = dawa_store.get_medication(body.medicationId)
    if not medication or medication["patient_id"] != body.patientId:
        raise HTTPException(
            status_code=404,
            detail=f"Medication {body.medicationId!r} not found for patient {body.patientId!r}",
        )

    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail="UPLIFT_ASSISTANT_ID not set. Run scripts/create_uplift_assistant.py first.",
        )
    if not settings.test_phone_number:
        raise HTTPException(
            status_code=503,
            detail="TEST_PHONE_NUMBER not set in Replit Secrets.",
        )

    dose_event = sched.schedule_demo_call(
        patient_id=body.patientId,
        medication_id=body.medicationId,
        delay_seconds=body.delaySeconds,
    )

    now_karachi = datetime.now(KARACHI_TZ)
    fire_at_str = dose_event["scheduledTime"]

    logger.info(
        "DAWA_DOSE_SCHEDULED demo event=%s delay=%ds", dose_event["id"], body.delaySeconds
    )

    return {
        "doseEventId":   dose_event["id"],
        "medicationId":  body.medicationId,
        "delaySeconds":  body.delaySeconds,
        "scheduledTime": fire_at_str,
        "serverTimeKarachi": now_karachi.isoformat(),
        "message": (
            f"DAWA will call Razia in {body.delaySeconds} second(s). "
            "Do not touch the app — the call will be placed automatically."
        ),
    }


# ---------------------------------------------------------------------------
# POST /api/dawa/demo/reset  (P2 NEW)
# ---------------------------------------------------------------------------

@router.post("/demo/reset")
async def demo_reset() -> dict:
    """
    Restore the demo to a clean state:
      ✓ Removes all dose_events (DAWA_DEMO_RESET)
      ✓ Cancels pending APScheduler jobs
      ✓ Preserves Razia Bibi patient record
      ✓ Preserves medications
      ✓ Preserves verified cues and patient memory
      ✗ Does NOT delete the database
      ✗ Does NOT affect P0-A routes or Uplift configuration
    """
    deleted_events = dawa_store.delete_demo_dose_events()
    cleared_jobs = sched.clear_pending_jobs()

    logger.info(
        "DAWA_DEMO_RESET events_deleted=%d jobs_cleared=%d",
        deleted_events, cleared_jobs,
    )

    # Verify seed data is intact
    patient = dawa_store.get_patient("razia-bibi")
    medications = dawa_store.get_medications_for_patient("razia-bibi")

    return {
        "doseEventsDeleted":      deleted_events,
        "schedulerJobsCleared":   cleared_jobs,
        "raziaPreserved":         patient is not None,
        "medicationsPreserved":   len(medications) == 2,
        "serverTimeKarachi":      datetime.now(KARACHI_TZ).isoformat(),
    }
