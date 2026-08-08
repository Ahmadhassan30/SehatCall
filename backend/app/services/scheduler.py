"""
DAWA P2 — In-process medication scheduler.

Design
------
Uses APScheduler 3.x AsyncIOScheduler to run on the same asyncio event loop
as FastAPI.  Two job types:

  1. Scan job   — runs every SCAN_INTERVAL_SECONDS; detects medications due at
                  their scheduled time (Asia/Karachi) and dispatches if idle.
  2. Demo jobs  — one-shot DateTrigger jobs created by schedule_demo_call();
                  fire after a caregiver-specified delay (15–300 s).

Single authoritative call dispatch
-----------------------------------
`dispatch_call_via_uplift()` is the ONE function that places a call through
Uplift.  The P1 manual endpoint (POST /api/dawa/demo-call), the demo scheduler,
and the auto-scan all go through this function.

Concurrency
-----------
Uplift hackathon allowance: one active outbound call per organisation.
A module-level asyncio.Lock prevents simultaneous dispatches.  When a call is
already in progress the scheduler logs DAWA_CALL_QUEUED and leaves the pending
dose event in the DB.  The next scan will pick it up once the lock is free.

Retry policy
------------
After dispatch, a status-check job fires after STATUS_CHECK_DELAY_SECONDS.
If the call reached a retryable terminal state and retry_count < MAX_RETRIES,
one retry is scheduled after RETRY_DELAY_SECONDS.

Retryable   : busy, no_answer, silent_pickup, voicemail, network_error, unreachable
Non-retryable: declined, wrong_number

Production note
---------------
This in-process scheduler is appropriate for a single Replit deployment.
It is NOT durable across restarts — scheduled jobs survive only while the
process is running.  A production system should use a durable task queue
(Celery + Redis, pg_cron, or similar).

Timezone
--------
All scheduling calculations use Asia/Karachi (UTC+5).  The server may run
in any timezone; KARACHI_TZ is never assumed from the OS.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import UPLIFT_BASE_URL, settings
from app.services import dawa_store
from app.services.call_context import build_call_context
from app.services import voice_catalog
from app.services import uplift as uplift_service

logger = logging.getLogger("dawa.scheduler")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KARACHI_TZ = ZoneInfo("Asia/Karachi")

SCAN_INTERVAL_SECONDS: int = 30
"""How often the background scan checks for due medications."""

STATUS_CHECK_DELAY_SECONDS: int = 120
"""Seconds after dispatch to check whether the call reached a terminal state."""

RETRY_DELAY_SECONDS: int = 30
"""Seconds to wait before retrying a retryable failed call (short for demo)."""

MAX_RETRIES: int = 1
"""Maximum number of automatic retries per dose event."""

# Failure reasons that warrant an automatic retry (after delay)
RETRYABLE_REASONS: frozenset[str] = frozenset(
    {"busy", "no_answer", "silent_pickup", "voicemail", "network_error", "unreachable"}
)

# Failure reasons that must NOT be automatically retried
NON_RETRYABLE_REASONS: frozenset[str] = frozenset({"declined", "wrong_number"})

# Call statuses that indicate an active (non-terminal) Uplift call
ACTIVE_CALL_STATUSES: frozenset[str] = frozenset(
    {"calling", "dispatched", "dialing", "ringing", "answered"}
)

# ---------------------------------------------------------------------------
# Module-level scheduler + concurrency state
# ---------------------------------------------------------------------------

_scheduler: AsyncIOScheduler | None = None
# One dispatch lock per patient, created on demand.
#
# A single global lock would serialise every caregiver's reminders: one patient
# mid-call would silently defer everyone else's dose to the next scan. Calls to
# different patients are genuinely independent, so they get independent locks.
_patient_locks: dict[str, asyncio.Lock] = {}


def _get_lock(patient_id: str) -> asyncio.Lock:
    lock = _patient_locks.get(patient_id)
    if lock is None:
        lock = asyncio.Lock()
        _patient_locks[patient_id] = lock
    return lock


def patient_lock(patient_id: str) -> asyncio.Lock:
    """
    The dispatch lock for one patient.

    Every path that can place a call — scheduled or manual — must hold this
    across the whole check-then-dial sequence. Checking for an active call
    without it lets two concurrent requests both see "idle" and both dial.
    Never acquired by dispatch_call_via_uplift itself, so callers cannot
    deadlock on it.
    """
    return _get_lock(patient_id)


# ---------------------------------------------------------------------------
# Public lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    """Start the APScheduler AsyncIOScheduler.  Call from FastAPI lifespan."""
    global _scheduler
    # Locks belong to the running event loop; drop any created under a previous
    # loop (notably between tests) so we never await a lock bound to a dead loop.
    _patient_locks.clear()
    _scheduler = AsyncIOScheduler(timezone=KARACHI_TZ)
    _scheduler.add_job(
        _scan_due_medications,
        IntervalTrigger(seconds=SCAN_INTERVAL_SECONDS, timezone=KARACHI_TZ),
        id="scan_due_medications",
        replace_existing=True,
        misfire_grace_time=30,
    )
    _scheduler.start()
    logger.info("DAWA_SCHEDULER_STARTED interval=%ds", SCAN_INTERVAL_SECONDS)


def stop_scheduler() -> None:
    """Stop the scheduler gracefully.  Call from FastAPI lifespan shutdown."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("DAWA_SCHEDULER_STOPPED")
    _scheduler = None


# ---------------------------------------------------------------------------
# Demo scheduling (public)
# ---------------------------------------------------------------------------

def schedule_demo_call(
    patient_id: str,
    medication_id: str,
    delay_seconds: int,
) -> dict:
    """
    Create a dose event and schedule a one-shot Uplift dispatch after
    `delay_seconds`.

    Called by POST /api/dawa/schedule-demo-call.
    Returns the new dose_event dict.
    """
    now_karachi = datetime.now(KARACHI_TZ)
    fire_at = now_karachi + timedelta(seconds=delay_seconds)
    scheduled_time_iso = fire_at.isoformat()

    # Create dose event (each demo call press = unique occurrence)
    event = dawa_store.create_dose_event(
        patient_id=patient_id,
        medication_id=medication_id,
        scheduled_time=scheduled_time_iso,
        call_status="scheduled",
    )
    event_id = event["id"]

    logger.info(
        "DAWA_DOSE_SCHEDULED demo event=%s delay=%ds fire_at=%s",
        event_id, delay_seconds, fire_at.isoformat(),
    )

    if _scheduler is None or not _scheduler.running:
        logger.warning("Scheduler not running — demo call queued but will not auto-fire")
        return event

    _scheduler.add_job(
        _scheduled_dispatch,
        DateTrigger(run_date=fire_at, timezone=KARACHI_TZ),
        args=[event_id, 0],
        id=f"demo_{event_id}",
        replace_existing=True,
    )
    return event


def _job_belongs_to_patient(job_id: str, patient_id: str) -> bool:
    """Demo job ids are 'demo_{dose_event_id}' — resolve the owner via the event."""
    event = dawa_store.get_dose_event(job_id[len("demo_"):])
    if not event:
        return False
    return (event.get("patientId") or event.get("patient_id")) == patient_id


def _pending_demo_jobs(patient_id: str | None) -> list:
    """Queued demo jobs, restricted to one patient's when a patient is given."""
    if _scheduler is None:
        return []
    jobs = [j for j in _scheduler.get_jobs() if j.id.startswith("demo_")]
    if patient_id is None:
        return jobs
    return [j for j in jobs if _job_belongs_to_patient(j.id, patient_id)]


def clear_pending_jobs(patient_id: str | None = None) -> int:
    """
    Remove queued demo jobs. Callers acting for a caregiver MUST pass
    patient_id: an unscoped reset would cancel every other caregiver's queued
    reminders too. patient_id=None is for process-wide teardown only.
    Returns the number of jobs removed.
    """
    jobs = _pending_demo_jobs(patient_id)
    for job in jobs:
        job.remove()
    if jobs:
        logger.info(
            "DAWA_DEMO_RESET cleared %d pending scheduler job(s) patient=%s",
            len(jobs), patient_id or "ALL",
        )
    return len(jobs)


def get_pending_job_info(patient_id: str | None = None) -> list[dict]:
    """
    Info about queued demo jobs, scoped to one patient when given — job
    metadata for other caregivers' patients must not reach a caregiver.
    """
    return [
        {
            "jobId": job.id,
            "nextRunTime": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in _pending_demo_jobs(patient_id)
    ]


# ---------------------------------------------------------------------------
# Single authoritative Uplift dispatch
# ---------------------------------------------------------------------------

async def dispatch_call_via_uplift(
    dose_event: dict,
    retry_count: int = 0,
) -> str:
    """
    THE single authoritative function that places a call through Uplift.

    Used by:
      - POST /api/dawa/demo-call  (manual)
      - schedule_demo_call()      (scheduled demo)
      - _scan_due_medications()   (auto-scan)

    Idempotency key: "{dose_event_id}:attempt:{retry_count}"
    — deterministic for the same dose occurrence and attempt number.

    Returns the Uplift callId.
    Raises ValueError if required secrets are missing.
    Raises httpx.HTTPStatusError on Uplift rejection.
    """
    patient_id = dose_event["patientId"]
    medication_id = dose_event["medicationId"]
    event_id = dose_event["id"]

    patient = dawa_store.get_patient(patient_id)
    if not patient:
        raise ValueError(f"Patient {patient_id!r} no longer exists.")

    # The number to dial belongs to the patient, and must have been proved.
    # This is the last line of defence: even if a dose event were created for an
    # unverified patient, nothing reaches the telephony provider here.
    phone = patient.get("phone_e164")
    if not phone:
        raise ValueError(f"Patient {patient_id!r} has no phone number.")
    if not patient.get("phone_verified_at"):
        raise ValueError(f"Patient {patient_id!r} has an unverified phone number.")

    # Correct drift before selecting the assistant. If an old TTS-only update
    # damaged the remote assistant, this clears its local reference so the same
    # dispatch can replace it safely below.
    await ensure_preferred_voice(patient_id)
    patient = dawa_store.get_patient(patient_id) or patient

    # Each patient dials through their own assistant, created with their chosen
    # voice already baked in.
    previous_assistant_id = patient.get("assistant_id")
    assistant_id = await uplift_service.get_or_create_patient_assistant(patient)
    if assistant_id != previous_assistant_id:
        desired_voice = patient.get("preferred_voice_id")
        if desired_voice and voice_catalog.is_valid_voice(desired_voice):
            _applied_voice_id[patient_id] = desired_voice

    # Build verified call context (P1 path — unchanged)
    ctx = build_call_context(patient_id, medication_id)

    # Deterministic idempotency key prevents duplicate calls for same dose+attempt
    idempotency_key = f"{event_id}:attempt:{retry_count}"

    # Mark as calling BEFORE the network hop so the UI updates immediately
    dawa_store.update_dose_event(event_id, call_status="calling")

    logger.info(
        "DAWA_CALL_DISPATCHED event=%s attempt=%d idempotencyKey=%s",
        event_id, retry_count, idempotency_key,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{UPLIFT_BASE_URL}/calls",
            json={
                "assistantId": assistant_id,
                "to": phone,
                "variables": ctx.variables,
                "additionalInstructions": ctx.additional_instructions,
            },
            headers={
                "Authorization": f"Bearer {settings.upliftai_api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
        )

    if not response.is_success:
        dawa_store.update_dose_event(event_id, call_status="failed")
        try:
            uplift_msg = response.json().get("message") or response.text
        except Exception:
            uplift_msg = response.text
        raise ValueError(f"Uplift rejected call: {uplift_msg} (HTTP {response.status_code})")

    data = response.json()
    call_id = (
        data.get("callId") or data.get("id") or data.get("sessionId") or "unknown"
    )
    dawa_store.update_dose_event(event_id, call_id=call_id, call_status="dispatched")

    # Schedule a status check to handle retry logic
    if _scheduler and _scheduler.running:
        check_at = datetime.now(KARACHI_TZ) + timedelta(seconds=STATUS_CHECK_DELAY_SECONDS)
        _scheduler.add_job(
            _check_call_status_and_maybe_retry,
            DateTrigger(run_date=check_at, timezone=KARACHI_TZ),
            args=[event_id, call_id, retry_count],
            id=f"status_check_{event_id}_{retry_count}",
            replace_existing=True,
        )

    return call_id


# ---------------------------------------------------------------------------
# Internal scheduler jobs
# ---------------------------------------------------------------------------

async def _scheduled_dispatch(dose_event_id: str, retry_count: int) -> None:
    """APScheduler calls this for demo and retry jobs."""
    event = dawa_store.get_dose_event(dose_event_id)
    if not event:
        logger.warning("_scheduled_dispatch: dose event %s not found", dose_event_id)
        return
    await _safe_dispatch(event, retry_count)


def has_active_call(patient_id: str | None = None) -> bool:
    """
    Return True if a DAWA dose event is currently in a non-terminal telephony
    state (dispatched / dialing / ringing / answered).

    Scoped to one patient when patient_id is given. Leaving it None keeps the
    old global meaning, which is what the admin/debug surfaces still want.

    This is the PRIMARY active-call guard.  The asyncio.Lock alone is NOT
    sufficient because the Lock is released as soon as POST /calls returns
    'dispatched', while the actual telephone call remains active for seconds
    or minutes longer (dialing → ringing → answered → completed/failed).
    """
    return bool(dawa_store.get_active_dose_events(patient_id))


async def _safe_dispatch(dose_event: dict, retry_count: int) -> None:
    """
    Two-layer concurrency guard before any Uplift dispatch.

    Layer 1 (primary)  — DB check via has_active_call():
        Inspects dose_events for any row in a non-terminal telephony state.
        Persists across asyncio.Lock release cycles.  If any active call
        exists, the pending event is left in the DB and logged DAWA_CALL_QUEUED;
        the next scheduler scan will retry once that call reaches a terminal state.

    Layer 2 (secondary) — asyncio.Lock:
        Guards against concurrent coroutines racing to call dispatch_call_via_uplift
        at the exact same moment.  Checked ONLY after Layer 1 passes, and
        re-verified after acquisition (double-checked locking).
    """
    patient_id = dose_event["patientId"]

    # ── Layer 1: DB-based active-call check (primary guard) ──────────────
    # Scoped to this patient: an elderly patient should never receive two
    # overlapping calls, but two different patients may be called at once.
    if has_active_call(patient_id):
        logger.info(
            "DAWA_CALL_QUEUED event=%s — active call in non-terminal state, next scan will retry",
            dose_event["id"],
        )
        return

    # ── Layer 2: asyncio.Lock (secondary race-condition guard) ────────────
    lock = _get_lock(patient_id)
    if lock.locked():
        logger.info(
            "DAWA_CALL_QUEUED event=%s — dispatch lock held by concurrent coroutine",
            dose_event["id"],
        )
        return
    async with lock:
        # Double-check: another coroutine may have slipped in between lock check and acquire
        if has_active_call(patient_id):
            logger.info(
                "DAWA_CALL_QUEUED event=%s — active call detected after lock acquire",
                dose_event["id"],
            )
            return
        try:
            await dispatch_call_via_uplift(dose_event, retry_count)
        except ValueError as exc:
            logger.error("DAWA_CALL_FAILED event=%s error=%s", dose_event["id"], exc)
            dawa_store.update_dose_event(dose_event["id"], call_status="failed")


async def _scan_due_medications(now_override: datetime | None = None) -> None:
    """
    Background scan: fires every SCAN_INTERVAL_SECONDS.

    1. Checks active calls — updates their status from Uplift if terminal.
    2. Dispatches any pending (queued) dose events.
    3. Detects newly due medications by comparing the current Karachi time
       against each medication's scheduled_time (HH:MM).
    """
    now = now_override or datetime.now(KARACHI_TZ)

    # ── Step 1: Update status of active calls (all patients) ─────────────
    # Status refresh is per dose event and touches no shared state, so it is
    # safe and cheaper to do in one pass rather than per patient.
    for ev in dawa_store.get_active_dose_events():
        if ev.get("callId"):
            await _refresh_call_status_from_uplift(ev)

    # ── Step 2: Per-patient dispatch ─────────────────────────────────────
    # Only patients with a verified phone are considered — an unverified number
    # never even reaches the due-medication logic.
    for patient in dawa_store.get_patients_with_verified_phone():
        try:
            await _scan_patient_for_due_medications(patient, now)
        except Exception:
            # One caregiver's bad data must never stop every other patient's
            # reminders. Log it and carry on with the next patient.
            logger.exception(
                "DAWA_SCAN_PATIENT_FAILED patient=%s", patient.get("id")
            )


async def _scan_patient_for_due_medications(patient: dict, now: datetime) -> None:
    """Dispatch queued or newly-due doses for exactly one patient."""
    patient_id = patient["id"]

    # Skip this patient if they already have a call in flight; other patients
    # in the same scan are unaffected.
    if _get_lock(patient_id).locked():
        return
    if dawa_store.get_active_dose_events(patient_id):
        return

    # ── Queued doses first ───────────────────────────────────────────────
    pending = dawa_store.get_pending_dose_events(patient_id)
    if pending:
        event = pending[0]
        logger.info("DAWA_DOSE_DUE event=%s (pending dispatch)", event["id"])
        await _safe_dispatch(event, event.get("retryCount", 0) or 0)
        return

    # ── Auto-detect due medications ──────────────────────────────────────
    # Only ACTIVE medications with auto-calling switched on are eligible.
    # A caregiver turning auto-call off must stop future automatic dispatches
    # while leaving manual "Call now" working.
    medications = [
        m for m in dawa_store.get_medications_for_patient(patient_id)
        if is_auto_call_eligible(m)
    ]
    today = now.date()

    for med in medications:
        try:
            hh, mm = med["schedule_time"].split(":")
            scheduled_dt = datetime(
                today.year, today.month, today.day,
                int(hh), int(mm),
                tzinfo=KARACHI_TZ,
            )
        except Exception:
            continue

        # Due window: [scheduled_time, scheduled_time + 5 min)
        if scheduled_dt <= now < scheduled_dt + timedelta(minutes=5):
            schedule_key = _make_schedule_key(
                patient_id, med["id"], today.isoformat(), med["schedule_time"]
            )
            event, created = dawa_store.get_or_create_scheduled_dose_event(
                schedule_key=schedule_key,
                patient_id=patient_id,
                medication_id=med["id"],
                scheduled_time=scheduled_dt.isoformat(),
            )
            if created:
                dawa_store.update_dose_event(event["id"], call_status="due")
                logger.info(
                    "DAWA_DOSE_DUE auto-detected patient=%s med=%s event=%s",
                    patient_id, med["id"], event["id"],
                )
                await _safe_dispatch(event, 0)
                # One call at a time per patient: leave the rest queued for the
                # next scan rather than dialling twice in a row.
                return


def assistant_id_for_event(event: dict) -> str | None:
    """
    The assistant a dose event's call actually ran on.

    Calls go out through the *patient's own* assistant, so status has to be read
    back from that same assistant. Querying the global one finds nothing, which
    leaves the event stuck in a non-terminal state forever — and because an
    active call blocks that patient, their next reminder would never dispatch.
    """
    patient_id = event.get("patientId") or event.get("patient_id")
    patient = dawa_store.get_patient(patient_id) if patient_id else None
    if patient and patient.get("assistant_id"):
        return patient["assistant_id"]
    # Events predating per-patient assistants ran on the shared one.
    return settings.uplift_assistant_id or None


async def fetch_recent_sessions(assistant_id: str, limit: int = 20) -> list[dict]:
    """Recent Uplift sessions for one assistant, or [] if unavailable."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{UPLIFT_BASE_URL}/realtime-assistants/{assistant_id}/sessions",
            params={"limit": limit},
            headers={"Authorization": f"Bearer {settings.upliftai_api_key}"},
        )
    if not resp.is_success:
        return []
    data = resp.json()
    return data if isinstance(data, list) else data.get("sessions", [])


async def _refresh_call_status_from_uplift(event: dict) -> None:
    """
    Fetch the live Uplift session status for an active call and update
    the dose_event if the call has reached a terminal state.
    Does not retry — that is handled by _check_call_status_and_maybe_retry.
    """
    call_id = event.get("callId")
    assistant_id = assistant_id_for_event(event)
    if not call_id or not assistant_id:
        return

    try:
        sessions = await fetch_recent_sessions(assistant_id)
        session = _find_session_for_call(sessions, call_id)
        if not session:
            return

        new_status = _derive_call_status(session)
        if new_status and new_status != event["callStatus"]:
            dawa_store.update_dose_event(event["id"], call_status=new_status)
            if new_status in ("completed", "failed"):
                logger.info(
                    "DAWA_CALL_TERMINAL event=%s callId=%s status=%s",
                    event["id"], _mask_call_id(call_id), new_status,
                )
    except Exception as exc:
        logger.debug("_refresh_call_status_from_uplift: %s", exc)


async def _check_call_status_and_maybe_retry(
    event_id: str,
    call_id: str,
    retry_count: int,
) -> None:
    """
    Fires STATUS_CHECK_DELAY_SECONDS after dispatch.
    Fetches terminal call state and schedules a retry if warranted.
    """
    event = dawa_store.get_dose_event(event_id)
    if not event:
        return

    failure_reason: str | None = None

    # Read status back from the assistant the call actually went out on.
    assistant_id = assistant_id_for_event(event)
    if assistant_id:
        try:
            sessions = await fetch_recent_sessions(assistant_id)
            session = _find_session_for_call(sessions, call_id)
            if session:
                failure_reason = (
                    session.get("failureReason") or session.get("failure_reason")
                )
                new_status = _derive_call_status(session)
                if new_status:
                    dawa_store.update_dose_event(event_id, call_status=new_status)
        except Exception as exc:
            logger.debug("_check_call_status_and_maybe_retry: %s", exc)

    # Decide retry
    if failure_reason in NON_RETRYABLE_REASONS:
        logger.info(
            "DAWA_CALL_TERMINAL non-retryable event=%s reason=%s",
            event_id, failure_reason,
        )
        dawa_store.update_dose_event(event_id, call_status="failed")
        return

    if failure_reason in RETRYABLE_REASONS and retry_count < MAX_RETRIES:
        new_retry = dawa_store.increment_retry_count(event_id)
        retry_at = datetime.now(KARACHI_TZ) + timedelta(seconds=RETRY_DELAY_SECONDS)
        logger.info(
            "DAWA_CALL_RETRY_SCHEDULED event=%s attempt=%d reason=%s fire_at=%s",
            event_id, new_retry, failure_reason, retry_at.isoformat(),
        )
        # Reset to pending so it can be dispatched
        dawa_store.update_dose_event(event_id, call_status="due")
        if _scheduler and _scheduler.running:
            updated_event = dawa_store.get_dose_event(event_id)
            _scheduler.add_job(
                _scheduled_dispatch,
                DateTrigger(run_date=retry_at, timezone=KARACHI_TZ),
                args=[event_id, new_retry],
                id=f"retry_{event_id}_{new_retry}",
                replace_existing=True,
            )
    elif retry_count >= MAX_RETRIES:
        logger.info(
            "DAWA_CALL_TERMINAL max retries reached event=%s", event_id,
        )
        dawa_store.update_dose_event(event_id, call_status="failed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_schedule_key(patient_id: str, medication_id: str, date_str: str, hhmm: str) -> str:
    """Deterministic key for one scheduled medication occurrence."""
    return f"{patient_id}:{medication_id}:{date_str}:{hhmm}"


_VALID_CALL_STATUSES = {"completed", "failed", "answered", "ringing", "dialing", "dispatched"}


def _derive_call_status(session: dict) -> str | None:
    """
    Map a real Uplift session object to a DAWA call_status string.

    Uses `state` as the authoritative field (real Uplift API schema).
    Falls back to timestamp inference only when `state` is absent.
    """
    # Primary: use the real Uplift `state` field
    state = (session.get("state") or "").lower()
    if state in _VALID_CALL_STATUSES:
        return state
    # Secondary: timestamp-based inference for sessions missing `state`
    if session.get("answeredAt"):
        return "answered"
    if session.get("ringingAt"):
        return "ringing"
    return None


def _find_session_for_call(sessions: list[dict], call_id: str) -> dict | None:
    """
    Correlate a stored call_id to a session in the Uplift sessions list.

    Uplift POST /calls may return callId, id, or sessionId — any of which
    might be stored as the dose event's callId.  GET sessions returns
    sessionId (and sometimes callId).

    Strategy:
    1. Exact match — call_id matches sessionId, callId, or id.
    2. Most-recent outbound telephony session — safe because DAWA's
       concurrency guard ensures at most one active call at a time.
    """
    # Restrict to outbound telephony where possible
    outbound = [
        s for s in sessions
        if s.get("channel") == "telephony" and s.get("direction") == "outbound"
    ] or sessions  # fall back to all if filter yields nothing

    # 1. Exact match
    for s in outbound:
        if call_id in (s.get("sessionId"), s.get("callId"), s.get("id")):
            return s

    # 2. Most recent by createdAt (single-active-call guarantee)
    try:
        return max(outbound, key=lambda s: s.get("createdAt") or "")
    except (ValueError, TypeError):
        return None


def _mask_call_id(call_id: str) -> str:
    """Mask call_id for logging (show first 8 chars + ***)."""
    if len(call_id) <= 8:
        return "***"
    return call_id[:8] + "***"


# ---------------------------------------------------------------------------
# P3 — auto-call eligibility, next-call computation, voice drift safety
# ---------------------------------------------------------------------------

def is_auto_call_eligible(medication: dict) -> bool:
    """
    A medication is automatically called only when it is active AND the
    caregiver has left automatic calling switched on.

    Manual "Call now" deliberately does NOT consult this — a caregiver can
    always place a call by hand.
    """
    return bool(medication.get("active", 1)) and bool(
        medication.get("auto_call_enabled", 1)
    )


def compute_next_call(
    patient_id: str,
    now: datetime | None = None,
) -> dict | None:
    """
    Return the next eligible upcoming automatic medication call.

    Authoritative: the UI must never compute scheduling truth itself.
    All arithmetic happens in Asia/Karachi.  If today's time has already
    passed, the occurrence rolls to tomorrow.

    Returns None when the patient has no auto-call-eligible medication.
    """
    current = now or datetime.now(KARACHI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KARACHI_TZ)
    else:
        current = current.astimezone(KARACHI_TZ)

    best: tuple[datetime, dict] | None = None

    for med in dawa_store.get_medications_for_patient(patient_id):
        if not is_auto_call_eligible(med):
            continue
        try:
            hh, mm = str(med["schedule_time"]).split(":")
            candidate = current.replace(
                hour=int(hh), minute=int(mm), second=0, microsecond=0
            )
        except Exception:
            continue  # malformed schedule_time is skipped, never guessed

        # Today's slot already passed → next occurrence is tomorrow
        if candidate <= current:
            candidate = candidate + timedelta(days=1)

        if best is None or candidate < best[0]:
            best = (candidate, med)

    if best is None:
        return None

    when, med = best
    return {
        "medicationId": med["id"],
        "nickname": med.get("nickname") or med["clinical_name"],
        "clinicalName": med["clinical_name"],
        "dosage": med["dosage"],
        "scheduleTime": med["schedule_time"],
        "scheduledFor": when.isoformat(),
        "secondsUntil": max(0, int((when - current).total_seconds())),
        "autoCallEnabled": bool(med.get("auto_call_enabled", 1)),
    }


# Last voice successfully applied to each patient's assistant this process.
# Keyed by patient: a single shared value would let one patient's sync suppress
# another patient's, leaving the second patient on the wrong voice.
_applied_voice_id: dict[str, str] = {}


def reset_voice_cache(patient_id: str | None = None) -> None:
    """
    Clear the applied-voice cache for one patient, or all of them.

    Callers acting for a caregiver should pass patient_id: clearing the whole
    map would force a redundant voice re-check on every other patient's next
    call.
    """
    if patient_id is None:
        _applied_voice_id.clear()
    else:
        _applied_voice_id.pop(patient_id, None)


async def ensure_preferred_voice(patient_id: str) -> str | None:
    """
    Make this patient's own Uplift assistant speak in their chosen voice.

    Guards against drift between patient.preferred_voice_id and the remote
    assistant without rebuilding the assistant or touching the Voice V2 prompt.

    Only ever PATCHes the assistant belonging to this patient, so concurrent
    calls to different patients cannot overwrite each other's voice. No-ops when
    the voice is already known to match, so a normal call costs zero extra
    Uplift requests.
    """
    patient = dawa_store.get_patient(patient_id)
    if not patient:
        return None
    desired = patient.get("preferred_voice_id")
    if not desired or not voice_catalog.is_valid_voice(desired):
        return None
    if _applied_voice_id.get(patient_id) == desired:
        return desired

    assistant_id = patient.get("assistant_id")
    if not assistant_id:
        # No assistant yet — it will be created with this voice baked in on the
        # first dispatch, so there is nothing to correct.
        return desired

    try:
        await uplift_service.update_assistant_voice(desired, assistant_id=assistant_id)
        _applied_voice_id[patient_id] = desired
        logger.info(
            "DAWA_VOICE_SYNCED patient=%s voiceId=%s", patient_id, desired
        )
    except Exception as exc:
        if getattr(exc, "dawa_code", None) == "UPLIFT_ASSISTANT_INCOMPLETE":
            # A historical TTS-only update may have replaced the complete
            # remote config. Keep that resource untouched; dropping only the
            # local reference lets this dispatch create a clean replacement.
            dawa_store.set_patient_assistant_id(patient_id, None)
            reset_voice_cache(patient_id)
            logger.warning(
                "DAWA_VOICE_SYNC_REQUIRES_REPLACEMENT patient=%s error=%s",
                patient_id,
                getattr(exc, "detail", str(exc)),
            )
        else:
            # A voice mismatch must never block a medication reminder — the
            # call still goes out, just in the assistant's current voice.
            logger.warning(
                "DAWA_VOICE_SYNC_FAILED patient=%s voiceId=%s error=%s",
                patient_id, desired, exc,
            )
    return desired
