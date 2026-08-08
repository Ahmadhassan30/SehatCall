---
name: P2 scheduler
description: APScheduler setup, test reload pattern, and key design decisions for the P2 proactive calling feature.
---

# P2 Scheduler

## Scheduler
APScheduler 3.x `AsyncIOScheduler` with `KARACHI_TZ = ZoneInfo("Asia/Karachi")`.
`start_scheduler()` / `stop_scheduler()` called from FastAPI lifespan in `main.py`.
Scan job fires every 30 s (`_scan_due_medications`); demo jobs are one-shot `DateTrigger`.

## Critical test reload pattern
`_make_p1_client` (and P2 equivalent) must reload `app.services.scheduler` (and `app.services.call_context`) in addition to the other modules. If scheduler is not reloaded, `scheduler.settings` holds the **pre-reload** settings object — `uplift_assistant_id` appears unset, causing 500 on `demo_call`.

**Why:** `scheduler.py` does `from app.config import settings` at module load time. After `importlib.reload(cfg_mod)`, the scheduler module still has the old settings binding unless it is also reloaded.

**How to apply:** Any test helper that does `monkeypatch.setenv("UPLIFT_ASSISTANT_ID", ...)` + `importlib.reload(cfg_mod)` must also call `importlib.reload(sched_mod)` BEFORE reloading `dawa_api_mod` and `main_mod`.

## Single dispatch path
`scheduler.dispatch_call_via_uplift(dose_event, retry_count)` is the ONE function that calls Uplift. Both manual `POST /api/dawa/demo-call` and scheduled calls use it. Tests that mock Uplift HTTP calls must patch `app.services.scheduler.httpx.AsyncClient` (not `app.api.dawa.httpx.AsyncClient`).

## Dose event idempotency (auto-scan)
`schedule_key = "{patient_id}:{medication_id}:{YYYY-MM-DD}:{HH:MM}"` — UNIQUE index on `dose_events.schedule_key`. `get_or_create_scheduled_dose_event` uses `INSERT OR IGNORE`. Demo calls each get a fresh event (no schedule_key needed for one-shot demo jobs).

## Test count
120 total (77 P0-A + 19 P1 + 24 P2) — all passing as of P2 delivery.
