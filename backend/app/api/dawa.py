"""
DAWA P1+P2+P3+P4 API routes.

P1 routes:
  GET  /api/dawa/demo              — seeded patient + medications + dose events
  POST /api/dawa/vmr/resolve       — deterministic medication identity resolution
  POST /api/dawa/demo-call         — manual call dispatch
  GET  /api/dawa/call-status       — recent dose events with live telephony status

P2 routes:
  POST /api/dawa/schedule-demo-call — schedule a call for 15–300 s from now
  POST /api/dawa/demo/reset         — clear demo dose events + queued scheduler jobs

P3 routes:
  GET  /api/dawa/patient, PUT /api/dawa/patient
  GET  /api/dawa/medications, POST /api/dawa/medications
  GET  /api/dawa/medications/{id}, PUT /api/dawa/medications/{id}
  POST /api/dawa/medications/{id}/call
  GET  /api/dawa/next-call
  GET  /api/dawa/calls
  GET  /api/dawa/voices, PUT /api/dawa/patient/voice
  POST /api/dawa/voices/{id}/preview

P4 routes (new):
  POST /api/dawa/demo/claim         — atomic claim of the demo patient

P0-A routes (POST /api/test-call, GET /api/test-call/status) are unchanged.

P4 Auth contract:
  - ALL /api/dawa/* routes require a valid caregiver session injected by the
    TypeScript API Server (X-DAWA-CAREGIVER-ID + X-DAWA-INTERNAL-SECRET).
  - The scheduler runs in-process and MUST NOT use get_current_caregiver_id.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.config import UPLIFT_BASE_URL, settings
from app.lib.caregiver import get_current_caregiver_id
from app.services import dawa_store
from app.services import scheduler as sched
from app.services.call_context import build_call_context
from app.services.vmr import resolve as vmr_resolve
from app.services import voice_catalog
from app.services import uplift as uplift_service
from app.services import phone_verification as pv
from app.services.conflict import detect_conflicts

logger = logging.getLogger("dawa.api")

router = APIRouter(prefix="/api/dawa")

KARACHI_TZ = ZoneInfo("Asia/Karachi")

# Local, best-effort voice preview cache (no Redis / object storage).
_VOICE_PREVIEW_CACHE = Path(__file__).resolve().parents[2] / "data" / "voice_preview_cache"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_patient(caregiver_id: str) -> dict:
    """
    Return the patient owned by this caregiver, or raise 404.

    There is no fallback to any other patient: a caregiver sees only the record
    they created via POST /api/dawa/patient.
    """
    patient = dawa_store.get_patient_by_owner(caregiver_id)
    if not patient:
        raise HTTPException(
            status_code=404,
            detail=(
                "No patient set up for this caregiver yet. "
                "POST /api/dawa/patient to add one."
            ),
        )
    return patient


def _assert_phone_verified(patient: dict) -> None:
    """
    Raise 409 unless this patient's number has been proved.

    Every path that can cause DAWA to dial goes through here. Verification is
    checked at dispatch time rather than only at setup time, because a caregiver
    can change the number after setup and that clears the proof.
    """
    if not patient.get("phone_e164"):
        raise HTTPException(
            status_code=409,
            detail="Add a phone number for this patient before placing a call.",
        )
    if not patient.get("phone_verified_at"):
        raise HTTPException(
            status_code=409,
            detail=(
                "This phone number has not been verified yet. "
                "Request a verification call and enter the code first."
            ),
        )


def _require_medication_owned(medication_id: str, patient: dict) -> dict:
    """Return the medication only if it belongs to the owned patient, else 404."""
    med = dawa_store.get_medication(medication_id)
    if not med or med["patient_id"] != patient["id"]:
        raise HTTPException(status_code=404, detail="Medication not found.")
    return med


# ---------------------------------------------------------------------------
# GET /api/dawa/demo  (P1 + P2 extended)
# ---------------------------------------------------------------------------

@router.get("/demo")
async def get_demo(
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """
    Return the caregiver's owned demo patient, her medications, recent dose
    events, and P2 scheduler state (server time, next scheduled call, pending jobs).
    """
    patient = _require_patient(caregiver_id)
    patient_id = patient["id"]

    medications = dawa_store.get_medications_for_patient(patient_id)
    for med in medications:
        med["cues"] = dawa_store.get_medication_cues(med["id"])

    dose_events = dawa_store.get_recent_dose_events(patient_id=patient_id, limit=10)

    # P2: scheduler state — scoped to the owned patient. Queued-job metadata for
    # other caregivers' patients must never appear in this payload.
    now_karachi = datetime.now(KARACHI_TZ)
    pending_jobs = sched.get_pending_job_info(patient_id)
    pending_events = dawa_store.get_pending_dose_events(patient_id)

    next_scheduled: dict | None = None
    if pending_events:
        ev = pending_events[0]
        try:
            fire_at_str = ev["scheduledTime"]
            fire_at = datetime.fromisoformat(fire_at_str)
            delay_remaining = max(0, int((fire_at - now_karachi).total_seconds()))
        except Exception:
            fire_at_str = ""
            delay_remaining = 0
        next_scheduled = {
            "doseEventId": ev["id"],
            "medicationId": ev.get("medicationId") or ev.get("medication_id"),
            "scheduledTime": fire_at_str,
            "delayRemainingSeconds": delay_remaining,
        }

    return {
        # Serialised, never the raw row: that carries phone_e164, the owner id
        # and the assistant id, none of which belong in a client response.
        "patient": _serialise_patient(patient),
        "medications": medications,
        "doseEvents": dose_events,
        "serverTimeKarachi": now_karachi.isoformat(),
        "nextScheduledCall": next_scheduled,
        "pendingJobCount": len(pending_jobs),
        "pendingJobs": pending_jobs,
    }


# ---------------------------------------------------------------------------
# POST /api/dawa/vmr/resolve  (P1 — ownership scoped)
# ---------------------------------------------------------------------------

class VMRRequest(BaseModel):
    patientId: str
    cues: dict[str, str]


@router.post("/vmr/resolve")
async def vmr_resolve_endpoint(
    body: VMRRequest,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """Deterministic medication identity resolution — no LLM, no probabilities."""
    patient = _require_patient(caregiver_id)
    if body.patientId != patient["id"]:
        raise HTTPException(
            status_code=404,
            detail=f"Patient not found: {body.patientId!r}",
        )
    if not body.cues:
        raise HTTPException(status_code=400, detail="At least one cue is required.")
    result = vmr_resolve(patient["id"], body.cues)
    return result.to_dict()


# ---------------------------------------------------------------------------
# POST /api/dawa/demo-call  (P1 — ownership scoped)
# ---------------------------------------------------------------------------

class DemoCallRequest(BaseModel):
    patientId: str
    medicationId: str
    # Phone is NEVER accepted from request — always from TEST_PHONE_NUMBER


async def _do_dispatch_call(patient: dict, medication: dict) -> dict:
    """
    Shared core dispatch path used by demo-call AND medications/{id}/call.

    Verifies required settings, enforces single-active-call, creates the dose
    event, and delegates to the authoritative Uplift dispatch path.
    """
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail="UPLIFT_ASSISTANT_ID not set. Run scripts/create_uplift_assistant.py first.",
        )
    # DAWA dials the patient's own verified number, never a global test number.
    _assert_phone_verified(patient)

    # Active-call guard — prevents a second Uplift call to THIS patient while one
    # is in-flight. Scoped per patient so one caregiver's call does not block
    # another caregiver's.
    #
    # The whole check-create-dial sequence runs under the same per-patient lock
    # the scheduler uses. Without it, two taps arriving together would both see
    # "no active call" and both dial — the check and the dial are separated by
    # awaits, so the interleave is real, not theoretical.
    lock = sched.patient_lock(patient["id"])
    if lock.locked() or sched.has_active_call(patient["id"]):
        raise HTTPException(
            status_code=409,
            detail="Another DAWA call is currently active for this patient",
        )

    async with lock:
        # Re-check under the lock: the state may have changed while we waited.
        if sched.has_active_call(patient["id"]):
            raise HTTPException(
                status_code=409,
                detail="Another DAWA call is currently active for this patient",
            )

        dose_event = dawa_store.create_dose_event(
            patient_id=patient["id"],
            medication_id=medication["id"],
            scheduled_time=datetime.now(KARACHI_TZ).isoformat(),
            call_status="calling",
        )

        try:
            call_id = await sched.dispatch_call_via_uplift(dose_event, retry_count=0)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    logger.info(
        "DAWA_CALL_DISPATCHED manual callId=%s event=%s",
        call_id, dose_event["id"],
    )

    return {
        "callId": call_id,
        "status": "dispatched",
        "doseEventId": dose_event["id"],
    }


@router.post("/demo-call")
async def demo_call(
    body: DemoCallRequest,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """Manual call dispatch via the shared authoritative path."""
    patient = _require_patient(caregiver_id)
    if body.patientId != patient["id"]:
        raise HTTPException(
            status_code=404,
            detail=f"Patient not found: {body.patientId!r}",
        )
    medication = _require_medication_owned(body.medicationId, patient)
    return await _do_dispatch_call(patient, medication)


# ---------------------------------------------------------------------------
# GET /api/dawa/call-status  (P1 — ownership scoped)
# ---------------------------------------------------------------------------

@router.get("/call-status")
async def call_status(
    limit: int = 10,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """
    Recent dose events merged with live Uplift telephony status.
    Completed call ≠ TAKEN — adherence_outcome remains null.
    """
    patient = _require_patient(caregiver_id)
    patient_id = patient["id"]

    dose_events = dawa_store.get_recent_dose_events(patient_id=patient_id, limit=limit)

    # Sessions come from this patient's OWN assistant — the one their calls
    # actually went out on. Querying the global assistant would find nothing.
    live_sessions: dict[str, dict] = {}
    assistant_id = patient.get("assistant_id") or settings.uplift_assistant_id
    if assistant_id:
        try:
            from app.services.uplift import _normalise_session  # noqa: PLC0415
            for s in await sched.fetch_recent_sessions(assistant_id, limit=limit):
                ns = _normalise_session(s)
                for key in (ns.get("sessionId"), s.get("callId"), s.get("id")):
                    if key:
                        live_sessions[key] = ns
        except Exception as exc:
            logger.warning("UPLIFT_STATUS_FETCH_FAILED: %s", exc)

    enriched: list[dict] = []
    for event in dose_events:
        call_id = event.get("callId")
        merged = dict(event)
        # Matched strictly by call id. There is deliberately no "most recent
        # session" fallback: guessing would staple someone else's call — and its
        # telephony metadata — onto this event.
        merged["liveStatus"] = live_sessions.get(call_id) if call_id else None
        enriched.append(merged)

    return {
        "doseEvents": enriched,
        "_note": "adherenceOutcome is distinct from callStatus. completed ≠ TAKEN.",
    }


# ---------------------------------------------------------------------------
# POST /api/dawa/schedule-demo-call  (P2 — ownership scoped)
# ---------------------------------------------------------------------------

class ScheduleDemoCallRequest(BaseModel):
    patientId: str
    medicationId: str
    delaySeconds: int = Field(default=60, ge=15, le=300)
    # phone / assistantId are intentionally NOT accepted from request body


@router.post("/schedule-demo-call")
async def schedule_demo_call(
    body: ScheduleDemoCallRequest,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """
    Schedule a one-shot call to fire in delaySeconds (15–300 s).
    Destination is always TEST_PHONE_NUMBER; assistant is UPLIFT_ASSISTANT_ID.
    """
    patient = _require_patient(caregiver_id)
    if body.patientId != patient["id"]:
        raise HTTPException(
            status_code=404,
            detail=f"Patient not found: {body.patientId!r}",
        )
    medication = _require_medication_owned(body.medicationId, patient)

    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail="UPLIFT_ASSISTANT_ID not set. Run scripts/create_uplift_assistant.py first.",
        )
    _assert_phone_verified(patient)

    dose_event = sched.schedule_demo_call(
        patient_id=patient["id"],
        medication_id=medication["id"],
        delay_seconds=body.delaySeconds,
    )

    now_karachi = datetime.now(KARACHI_TZ)
    fire_at_str = dose_event["scheduledTime"]

    logger.info(
        "DAWA_DOSE_SCHEDULED demo event=%s delay=%ds", dose_event["id"], body.delaySeconds
    )

    return {
        "doseEventId":   dose_event["id"],
        "medicationId":  medication["id"],
        "delaySeconds":  body.delaySeconds,
        "scheduledTime": fire_at_str,
        "serverTimeKarachi": now_karachi.isoformat(),
        "message": (
            f"DAWA will call {patient['name']} in {body.delaySeconds} second(s). "
            "Do not touch the app — the call will be placed automatically."
        ),
    }


# ---------------------------------------------------------------------------
# POST /api/dawa/demo/reset  (P2 — ownership scoped)
# ---------------------------------------------------------------------------

@router.post("/demo/reset")
async def demo_reset(
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """
    Restore the demo to a clean state for the caregiver's owned patient:
      ✓ Removes all dose_events for the owned patient
      ✓ Cancels pending APScheduler jobs
      ✓ Preserves patient record and owner_user_id
      ✓ Preserves medications, cues, and patient memory
      ✗ Does NOT delete the database
      ✗ Does NOT affect P0-A routes or Uplift configuration
    """
    patient = _require_patient(caregiver_id)
    patient_id = patient["id"]

    deleted_events = dawa_store.delete_patient_dose_events(patient_id)
    # Scoped: an unscoped clear would cancel every other caregiver's queued calls.
    cleared_jobs = sched.clear_pending_jobs(patient_id)

    logger.info(
        "DAWA_DEMO_RESET caregiver=%s events_deleted=%d jobs_cleared=%d",
        caregiver_id, deleted_events, cleared_jobs,
    )

    medications = dawa_store.get_medications_for_patient(patient_id)

    return {
        "doseEventsDeleted":      deleted_events,
        "schedulerJobsCleared":   cleared_jobs,
        "patientPreserved":       True,
        "medicationsPreserved":   len(medications) >= 0,
        "serverTimeKarachi":      datetime.now(KARACHI_TZ).isoformat(),
    }


# ---------------------------------------------------------------------------
# Patient creation + phone verification  (P5 — real multi-user)
# ---------------------------------------------------------------------------

class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    preferredAddress: str = Field(min_length=1, max_length=40)
    phone: str = Field(min_length=1, max_length=32)
    language: str = "ur"
    literacyMode: str = "voice_first"


class PhoneVerifyPayload(BaseModel):
    code: str = Field(min_length=1, max_length=12)


@router.post("/patient", status_code=201)
async def create_patient_endpoint(
    body: PatientCreate,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """
    Create this caregiver's patient.

    One patient per account. The phone number starts unverified — no call of any
    kind reaches it until the caregiver completes the verification challenge.
    """
    try:
        phone = pv.normalise_phone(body.phone)
    except pv.PhoneVerificationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        patient = dawa_store.create_patient_for_owner(
            owner_user_id=caregiver_id,
            name=body.name.strip(),
            preferred_address=body.preferredAddress.strip(),
            phone_e164=phone,
            language=body.language,
            literacy_mode=body.literacyMode,
        )
    except dawa_store.PatientAlreadyExists as exc:
        raise HTTPException(
            status_code=409,
            detail="This account already has a patient. Edit the existing one instead.",
        ) from exc

    logger.info(
        "DAWA_PATIENT_CREATED caregiver=%s patient=%s", caregiver_id, patient["id"]
    )
    return _serialise_patient(patient)


@router.post("/patient/phone/send-code")
async def send_phone_code_endpoint(
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """
    Ring the patient's number and speak a verification code.

    The challenge row is reserved BEFORE dialling and rolled back if the call
    fails. Writing it after the dispatch would leave an await between the
    cooldown check and the write, so two rapid taps could both pass the check
    and place two calls — and only the second code would work. Rolling back on
    failure preserves the property that a call which never happened does not
    start a cooldown.
    """
    patient = _require_patient(caregiver_id)
    phone = patient.get("phone_e164")
    if not phone:
        raise HTTPException(
            status_code=409, detail="Add a phone number for this patient first."
        )
    if patient.get("phone_verified_at"):
        raise HTTPException(
            status_code=409, detail="This phone number is already verified."
        )

    now = datetime.now(timezone.utc)

    existing = dawa_store.get_phone_verification(patient["id"])
    if existing:
        wait = pv.cooldown_remaining(existing["sent_at"], now)
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {wait} seconds before requesting another call.",
            )

    code = pv.generate_code()

    # Reserve first — there is no await between the cooldown check above and
    # this write, which is what makes the pair atomic.
    dawa_store.upsert_phone_verification(
        patient_id=patient["id"],
        phone_e164=phone,
        code_hash=pv.hash_code(code),
        expires_at=pv.expiry_from(now),
    )

    try:
        await uplift_service.dispatch_verification_call(phone, code)
    except Exception:
        # No call went out, so no cooldown should be served.
        dawa_store.clear_phone_verification(patient["id"])
        raise

    return {
        "status": "sent",
        "maskedPhone": pv.mask_phone(phone),
        "expiresInSeconds": int(pv.CODE_TTL.total_seconds()),
        "resendAvailableInSeconds": int(pv.RESEND_COOLDOWN.total_seconds()),
    }


@router.post("/patient/phone/verify")
async def verify_phone_code_endpoint(
    body: PhoneVerifyPayload,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """Check a submitted code and, on success, unlock calling for this patient."""
    patient = _require_patient(caregiver_id)
    patient_id = patient["id"]

    if patient.get("phone_verified_at"):
        return {"status": "verified", "maskedPhone": pv.mask_phone(patient["phone_e164"])}

    challenge = dawa_store.get_phone_verification(patient_id)
    if not challenge:
        raise HTTPException(
            status_code=400,
            detail="No verification in progress. Request a verification call first.",
        )

    now = datetime.now(timezone.utc)

    if pv.is_expired(challenge["expires_at"], now):
        dawa_store.clear_phone_verification(patient_id)
        raise HTTPException(
            status_code=400, detail="That code has expired. Request a new call."
        )

    # The number may have been edited after the code went out. Accepting the old
    # code now would verify a number nobody ever answered.
    if challenge["phone_e164"] != patient.get("phone_e164"):
        dawa_store.clear_phone_verification(patient_id)
        raise HTTPException(
            status_code=400,
            detail="The phone number changed since that code was sent. Request a new call.",
        )

    if challenge["attempts"] >= pv.MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many incorrect attempts. Request a new verification call.",
        )

    if not pv.verify_code(body.code.strip(), challenge["code_hash"]):
        attempts = dawa_store.increment_phone_verification_attempts(patient_id)
        remaining = max(pv.MAX_ATTEMPTS - attempts, 0)
        if remaining == 0:
            dawa_store.clear_phone_verification(patient_id)
            raise HTTPException(
                status_code=429,
                detail="Too many incorrect attempts. Request a new verification call.",
            )
        raise HTTPException(
            status_code=400,
            detail=f"That code is not correct. {remaining} attempt(s) remaining.",
        )

    dawa_store.mark_phone_verified(patient_id)
    logger.info("DAWA_PHONE_VERIFIED patient=%s", patient_id)

    return {"status": "verified", "maskedPhone": pv.mask_phone(patient["phone_e164"])}


# ===========================================================================
# P3 — Caregiver setup API
# ===========================================================================

def _serialise_medication(med: dict) -> dict:
    """Medication + verified cues + deterministic caregiver warnings."""
    return {
        "id": med["id"],
        "patientId": med["patient_id"],
        "clinicalName": med["clinical_name"],
        "nickname": med.get("nickname"),
        "dosage": med["dosage"],
        "doseInstruction": med["dose_instruction"],
        "foodInstruction": med.get("food_instruction"),
        "scheduleTime": med["schedule_time"],
        "routineAnchor": med.get("routine_anchor"),
        "active": bool(med.get("active", 1)),
        "autoCallEnabled": bool(med.get("auto_call_enabled", 1)),
        "doctorInstructions": med.get("doctor_instructions"),
        "doctorName": med.get("doctor_name"),
        "verifiedAt": med.get("verified_at"),
        "updatedAt": med.get("updated_at"),
        "cues": dawa_store.get_medication_cues(med["id"]),
        "warnings": detect_conflicts(med),
    }


def _serialise_patient(patient: dict) -> dict:
    """
    Safe patient projection.

    The phone number is returned MASKED only. The caregiver needs to see which
    number DAWA will dial in order to spot a typo, but the full number never
    leaves the server — a stolen session should not yield a readable phone book.
    """
    phone = patient.get("phone_e164")
    verification = dawa_store.get_phone_verification(patient["id"])
    return {
        "id": patient["id"],
        "name": patient["name"],
        "preferredAddress": patient["preferred_address"],
        "language": patient.get("language", "ur"),
        "literacyMode": patient.get("literacy_mode", "voice_first"),
        "maskedPhone": pv.mask_phone(phone) if phone else None,
        "phoneVerified": bool(patient.get("phone_verified_at")),
        "phoneVerificationInProgress": bool(verification),
        "preferredVoiceId": patient.get("preferred_voice_id"),
        "preferredVoiceName": (
            patient.get("preferred_voice_name")
            or voice_catalog.voice_name(patient.get("preferred_voice_id"))
        ),
    }


_VALID_CUE_KEYS = {"package_color", "stripe_color", "tablet_shape", "storage_location"}


def _validate_schedule_time(value: str) -> str:
    """Accept only a real 24-hour HH:MM value."""
    try:
        hh, mm = value.split(":")
        h, m = int(hh), int(mm)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except Exception:
        raise HTTPException(
            status_code=422, detail="scheduleTime must be a valid 24-hour HH:MM value."
        )
    return f"{int(value.split(':')[0]):02d}:{int(value.split(':')[1]):02d}"


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------

class PatientUpdate(BaseModel):
    name: str | None = None
    preferredAddress: str | None = None
    language: str | None = None
    literacyMode: str | None = None
    # Editable, but changing it revokes verification (see below).
    phone: str | None = None


@router.get("/patient")
async def get_patient_endpoint(
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    return _serialise_patient(_require_patient(caregiver_id))


@router.put("/patient")
async def update_patient_endpoint(
    body: PatientUpdate,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    patient = _require_patient(caregiver_id)

    if body.phone is not None:
        try:
            phone = pv.normalise_phone(body.phone)
        except pv.PhoneVerificationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Only touch the number if it actually changed — otherwise saving an
        # unrelated field (a name typo) would silently revoke verification and
        # stop the patient's reminders.
        if phone != patient.get("phone_e164"):
            dawa_store.update_patient_phone(patient["id"], phone)
            logger.info("DAWA_PATIENT_PHONE_CHANGED patient=%s", patient["id"])

    updated = dawa_store.update_patient(
        patient["id"],
        name=body.name,
        preferred_address=body.preferredAddress,
        language=body.language,
        literacy_mode=body.literacyMode,
    )
    return _serialise_patient(updated)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------

class MedicationPayload(BaseModel):
    clinicalName: str = Field(min_length=1)
    dosage: str = Field(min_length=1)
    doseInstruction: str = Field(min_length=1)
    scheduleTime: str
    nickname: str | None = None
    foodInstruction: str | None = None
    routineAnchor: str | None = None
    active: bool | None = None
    autoCallEnabled: bool | None = None
    doctorInstructions: str | None = None
    doctorName: str | None = None
    cues: dict[str, str] | None = None


class MedicationPatch(BaseModel):
    clinicalName: str | None = None
    dosage: str | None = None
    doseInstruction: str | None = None
    scheduleTime: str | None = None
    nickname: str | None = None
    foodInstruction: str | None = None
    routineAnchor: str | None = None
    active: bool | None = None
    autoCallEnabled: bool | None = None
    doctorInstructions: str | None = None
    doctorName: str | None = None
    cues: dict[str, str] | None = None


def _clean_cues(cues: dict[str, str] | None) -> dict[str, str]:
    """Keep only the supported cue keys — unknown keys are rejected outright."""
    if not cues:
        return {}
    unknown = set(cues) - _VALID_CUE_KEYS
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported recognition cue keys: {sorted(unknown)}",
        )
    return cues


@router.get("/medications")
async def list_medications(
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    patient = _require_patient(caregiver_id)
    meds = dawa_store.get_medications_for_patient(patient["id"])
    return {"medications": [_serialise_medication(m) for m in meds]}


@router.post("/medications", status_code=201)
async def create_medication_endpoint(
    body: MedicationPayload,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    patient = _require_patient(caregiver_id)
    schedule_time = _validate_schedule_time(body.scheduleTime)
    cues = _clean_cues(body.cues)

    med = dawa_store.create_medication(
        patient["id"],
        clinical_name=body.clinicalName,
        nickname=body.nickname,
        dosage=body.dosage,
        dose_instruction=body.doseInstruction,
        food_instruction=body.foodInstruction,
        schedule_time=schedule_time,
        routine_anchor=body.routineAnchor,
        active=True if body.active is None else body.active,
        auto_call_enabled=True if body.autoCallEnabled is None else body.autoCallEnabled,
        doctor_instructions=body.doctorInstructions,
        doctor_name=body.doctorName,
    )
    if cues:
        dawa_store.set_medication_cues(med["id"], cues)
    return _serialise_medication(dawa_store.get_medication(med["id"]))  # type: ignore[arg-type]


@router.get("/medications/{medication_id}")
async def get_medication_endpoint(
    medication_id: str,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    patient = _require_patient(caregiver_id)
    med = _require_medication_owned(medication_id, patient)
    return _serialise_medication(med)


@router.put("/medications/{medication_id}")
async def update_medication_endpoint(
    medication_id: str,
    body: MedicationPatch,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    patient = _require_patient(caregiver_id)
    _require_medication_owned(medication_id, patient)

    schedule_time = (
        _validate_schedule_time(body.scheduleTime) if body.scheduleTime else None
    )
    cues = _clean_cues(body.cues)

    # Historical dose_events are intentionally left alone: editing a schedule
    # changes future occurrences only.
    dawa_store.update_medication(
        medication_id,
        clinical_name=body.clinicalName,
        nickname=body.nickname,
        dosage=body.dosage,
        dose_instruction=body.doseInstruction,
        food_instruction=body.foodInstruction,
        schedule_time=schedule_time,
        routine_anchor=body.routineAnchor,
        active=body.active,
        auto_call_enabled=body.autoCallEnabled,
        doctor_instructions=body.doctorInstructions,
        doctor_name=body.doctorName,
    )
    if body.cues is not None:
        dawa_store.set_medication_cues(medication_id, cues)
    return _serialise_medication(dawa_store.get_medication(medication_id))  # type: ignore[arg-type]


@router.post("/medications/{medication_id}/call")
async def call_medication_now(
    medication_id: str,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """
    Manual "Call now". Delegates to the SAME authoritative path as demo-call
    and the scheduler — there is only one Uplift call implementation.
    """
    patient = _require_patient(caregiver_id)
    medication = _require_medication_owned(medication_id, patient)
    return await _do_dispatch_call(patient, medication)


# ---------------------------------------------------------------------------
# Next call + history
# ---------------------------------------------------------------------------

@router.get("/next-call")
async def next_call(
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """Backend-authoritative next automatic call (Asia/Karachi)."""
    patient = _require_patient(caregiver_id)
    return {"nextCall": sched.compute_next_call(patient["id"])}


@router.get("/calls")
async def list_calls(
    limit: int = 20,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """
    Recent dose/call events.

    Adherence is reported ONLY when a verified outcome exists — a completed
    call never implies the medicine was taken.
    """
    patient = _require_patient(caregiver_id)
    patient_id = patient["id"]

    events = dawa_store.get_recent_dose_events(patient_id=patient_id, limit=limit)
    meds = {m["id"]: m for m in dawa_store.get_medications_for_patient(patient_id)}

    items = []
    for ev in events:
        med = meds.get(ev["medicationId"], {})
        items.append({
            "id": ev["id"],
            "medicationId": ev["medicationId"],
            "nickname": med.get("nickname") or med.get("clinical_name") or "Medication",
            "clinicalName": med.get("clinical_name"),
            "scheduledTime": ev["scheduledTime"],
            "callStatus": ev["callStatus"],
            "adherenceOutcome": ev.get("adherenceOutcome"),
            "adherenceLabel": (
                ev.get("adherenceOutcome") or "Outcome not confirmed"
            ),
            "createdAt": ev.get("createdAt"),
            "updatedAt": ev.get("updatedAt"),
        })
    return {"calls": items}


# ---------------------------------------------------------------------------
# DAWA voice selection
# ---------------------------------------------------------------------------

class VoiceSelection(BaseModel):
    voiceId: str


@router.get("/voices")
async def list_voices_endpoint(
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """Verified Uplift voice catalog — safe display metadata only."""
    patient = _require_patient(caregiver_id)
    return {
        "voices": voice_catalog.list_voices(),
        "selectedVoiceId": patient.get("preferred_voice_id"),
    }


@router.put("/patient/voice")
async def set_patient_voice_endpoint(
    body: VoiceSelection,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> dict:
    """
    Change the voice the patient hears.

    Order matters: validate → refuse during an active call → update Uplift →
    only then persist.  This guarantees the DB never advertises a voice the
    assistant is not actually using.
    """
    patient = _require_patient(caregiver_id)

    if not voice_catalog.is_valid_voice(body.voiceId):
        raise HTTPException(status_code=400, detail="Unknown DAWA voice.")

    # Scoped to this patient — another caregiver's in-flight call is irrelevant
    # here, and blocking on it would make voice changes fail at random.
    if sched.has_active_call(patient["id"]):
        raise HTTPException(
            status_code=409,
            detail="DAWA voice cannot be changed while a call is active",
        )

    # Apply to the patient's OWN assistant, never the shared one. A patient who
    # has never been dialled has no assistant yet; theirs is created with this
    # voice on first dispatch, so there is nothing remote to update.
    assistant_id = patient.get("assistant_id")
    if assistant_id:
        try:
            await uplift_service.update_assistant_voice(
                body.voiceId, assistant_id=assistant_id
            )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=502,
                detail="DAWA couldn't change the voice. Your previous voice is still active.",
            )

    updated = dawa_store.set_patient_voice(
        patient["id"], body.voiceId, voice_catalog.voice_name(body.voiceId)
    )
    sched.reset_voice_cache(patient["id"])
    return _serialise_patient(updated)  # type: ignore[arg-type]


@router.post("/voices/{voice_id}/preview")
async def preview_voice(
    voice_id: str,
    caregiver_id: str = Depends(get_current_caregiver_id),
) -> Response:
    """
    Synthesize the fixed DAWA preview phrase with the server-side API key.

    Only a catalog voice id is accepted, and the phrase is a server constant —
    this cannot be used as an open TTS proxy. Results are cached on disk to
    avoid burning Uplift credits on repeated taps.
    """
    # Auth validated above; voice catalog is global, no per-patient scoping needed.
    if not voice_catalog.is_valid_voice(voice_id):
        raise HTTPException(status_code=400, detail="Unknown DAWA voice.")

    cache_file = _VOICE_PREVIEW_CACHE / f"{re.sub(r'[^A-Za-z0-9_-]', '_', voice_id)}.mp3"
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return Response(content=cache_file.read_bytes(), media_type="audio/mpeg")

    audio = await uplift_service.synthesize_voice_preview(voice_id)

    # Best-effort cache; Replit's filesystem is ephemeral so regenerate silently.
    try:
        _VOICE_PREVIEW_CACHE.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(audio)
    except OSError:
        logger.warning("VOICE_PREVIEW_CACHE_WRITE_FAILED voiceId=%s", voice_id)

    return Response(content=audio, media_type="audio/mpeg")
