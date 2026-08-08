"""
DAWA P2 — FastAPI application entry point.

Registers:
  GET  /health                         — liveness probe
  POST /api/test-call                  — P0-A dispatch
  GET  /api/test-call/status           — P0-A status
  GET  /api/dawa/demo                  — P1+P2 demo state
  POST /api/dawa/vmr/resolve           — P1 VMR
  POST /api/dawa/demo-call             — P1 manual call
  GET  /api/dawa/call-status           — P1 telephony status
  POST /api/dawa/schedule-demo-call    — P2 proactive scheduling
  POST /api/dawa/demo/reset            — P2 demo reset

P0-A conformance preserved:
  GET /health → {"status": "ok", "service": "dawa-p0"} — no extra keys
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.test_call import router as test_call_router
from app.api.dawa import router as dawa_router
from app.services.dawa_store import init_dawa_db, seed_demo_data
from app.services import scheduler as sched

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("dawa")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise DB, seed demo data, start scheduler on startup."""
    logger.info("DAWA_STARTUP: initialising P1/P2 database tables")
    init_dawa_db()
    seed_demo_data()
    logger.info("DAWA_STARTUP: demo data ready (razia-bibi)")

    sched.start_scheduler()

    yield

    sched.stop_scheduler()
    logger.info("DAWA_SHUTDOWN: goodbye")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DAWA P2",
    description=(
        "Uplift AI phone call integration — proactive Urdu medication reminders. "
        "P0-A conformance preserved; P2 adds in-process scheduler and demo controls."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(test_call_router)
app.include_router(dawa_router)


@app.get("/health")
async def health() -> dict:
    """
    Liveness probe.
    P0-A CONFORMANCE: returns exactly {"status": "ok", "service": "dawa-p0"}.
    """
    return {"status": "ok", "service": "dawa-p0"}
