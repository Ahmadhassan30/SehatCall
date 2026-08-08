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
_dispatch_lock: asyncio.Lock | None = None   # Created in start_scheduler()


def _get_lock() -> asyncio.Lock:
    global _dispatch_lock
    if _dispatch_lock is None:
        _dispatch_lock = asyncio.Lock()
    return _dispatch_lock


# ---------------------------------------------------------------------------
# Public lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    """Start the APScheduler AsyncIOScheduler.  Call from FastAPI lifespan."""
    global _scheduler, _dispatch_lock
    _dispatch_lock = asyncio.Lock()
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


def clear_pending_jobs() -> int:
    """
    Remove all pending scheduler jobs whose id starts with 'demo_'.
    Used by the demo reset endpoint.
    Returns the number of jobs removed.
    """
    if _scheduler is None:
        return 0
    jobs = _scheduler.get_jobs()
    removed = 0
    for job in jobs:
        if job.id.startswith("demo_"):
            job.remove()
            removed += 1
    if removed:
        logger.info("DAWA_DEMO_RESET cleared %d pending scheduler job(s)", removed)
    return removed


def get_pending_job_info() -> list[dict]:
    """Return info about pending demo jobs (for demo state endpoint)."""
    if _scheduler is None:
        return []
    jobs = []
    for job in _scheduler.get_jobs():
        if job.id.startswith("demo_"):
            next_run = job.next_run_time
            jobs.append({
                "jobId": job.id,
                "nextRunTime": next_run.isoformat() if next_run else None,
            })
    return jobs


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
    if not settings.uplift_assistant_id:
        raise ValueError(
            "UPLIFT_ASSISTANT_ID not set. Run scripts/create_uplift_assistant.py first."
        )
    if not settings.test_phone_number:
        raise ValueError("TEST_PHONE_NUMBER not set in Replit Secrets.")

    patient_id = dose_event["patientId"]
    medication_id = dose_event["medicationId"]
    event_id = dose_event["id"]

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
                "assistantId": settings.uplift_assistant_id,
                "to": settings.test_phone_number,
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


async def _safe_dispatch(dose_event: dict, retry_count: int) -> None:
    """Acquire the dispatch lock and call Uplift, or queue if busy."""
    lock = _get_lock()
    if lock.locked():
        logger.info(
            "DAWA_CALL_QUEUED event=%s — another call in progress, will retry at next scan",
            dose_event["id"],
        )
        return
    async with lock:
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
    lock = _get_lock()

    # ── Step 1: Update status of active calls ────────────────────────────
    active_events = dawa_store.get_active_dose_events()
    for ev in active_events:
        if ev.get("callId"):
            await _refresh_call_status_from_uplift(ev)

    # If a call is still active, skip dispatch
    if lock.locked():
        return
    still_active = dawa_store.get_active_dose_events()
    if still_active:
        return

    # ── Step 2: Dispatch any pending dose events ─────────────────────────
    pending = dawa_store.get_pending_dose_events()
    if pending:
        event = pending[0]
        logger.info("DAWA_DOSE_DUE event=%s (pending dispatch)", event["id"])
        await _safe_dispatch(event, event.get("retryCount", 0) or 0)
        return

    # ── Step 3: Auto-detect due medications ──────────────────────────────
    medications = dawa_store.get_medications_for_patient("razia-bibi")
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
                "razia-bibi", med["id"], today.isoformat(), med["schedule_time"]
            )
            event, created = dawa_store.get_or_create_scheduled_dose_event(
                schedule_key=schedule_key,
                patient_id="razia-bibi",
                medication_id=med["id"],
                scheduled_time=scheduled_dt.isoformat(),
            )
            if created:
                dawa_store.update_dose_event(event["id"], call_status="due")
                logger.info(
                    "DAWA_DOSE_DUE auto-detected med=%s event=%s",
                    med["id"], event["id"],
                )
                await _safe_dispatch(event, 0)


async def _refresh_call_status_from_uplift(event: dict) -> None:
    """
    Fetch the live Uplift session status for an active call and update
    the dose_event if the call has reached a terminal state.
    Does not retry — that is handled by _check_call_status_and_maybe_retry.
    """
    call_id = event.get("callId")
    if not call_id or not settings.uplift_assistant_id:
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{UPLIFT_BASE_URL}/realtime-assistants/{settings.uplift_assistant_id}/sessions",
                params={"limit": 20},
                headers={"Authorization": f"Bearer {settings.upliftai_api_key}"},
            )
        if not resp.is_success:
            return
        data = resp.json()
        sessions = data if isinstance(data, list) else data.get("sessions", [])
        session = next((s for s in sessions if s.get("callId") == call_id or s.get("id") == call_id), None)
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

    if settings.uplift_assistant_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{UPLIFT_BASE_URL}/realtime-assistants/{settings.uplift_assistant_id}/sessions",
                    params={"limit": 20},
                    headers={"Authorization": f"Bearer {settings.upliftai_api_key}"},
                )
            if resp.is_success:
                data = resp.json()
                sessions = data if isinstance(data, list) else data.get("sessions", [])
                session = next(
                    (s for s in sessions if s.get("callId") == call_id or s.get("id") == call_id),
                    None,
                )
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


def _derive_call_status(session: dict) -> str | None:
    """Map Uplift session flags to a DAWA call_status string."""
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


def _mask_call_id(call_id: str) -> str:
    """Mask call_id for logging (show first 8 chars + ***)."""
    if len(call_id) <= 8:
        return "***"
    return call_id[:8] + "***"
