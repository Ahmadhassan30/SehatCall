"""
DAWA P1 — FastAPI application entry point.

Registers:
  GET  /health                     — liveness probe, no external dependencies
  POST /api/test-call              — P0-A: dispatch Urdu outbound call
  GET  /api/test-call/status       — P0-A: inspect recent Uplift sessions
  GET  /api/dawa/demo              — P1: seeded patient + medications + dose events
  POST /api/dawa/vmr/resolve       — P1: deterministic medication identity resolution
  POST /api/dawa/demo-call         — P1: build verified context and dispatch call
  GET  /api/dawa/call-status       — P1: recent dose events with telephony lifecycle

P0-A conformance contract is fully preserved:
  GET /health   → {"status": "ok", "service": "dawa-p0"} — no extra keys
  POST /api/test-call   → no auth, no body, {"callId", "status"} only
  GET  /api/test-call/status → no auth, queries Uplift directly
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.test_call import router as test_call_router
from app.api.dawa import router as dawa_router
from app.services.dawa_store import init_dawa_db, seed_demo_data

# ---------------------------------------------------------------------------
# Logging — structured JSON-friendly output
# ---------------------------------------------------------------------------

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("dawa")


# ---------------------------------------------------------------------------
# Lifespan — initialise P1 database tables on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialise the P1 SQLite schema and seed the demo patient on startup.
    Safe to call on every restart (all operations are idempotent).
    """
    logger.info("DAWA_STARTUP: initialising P1 database tables")
    init_dawa_db()
    seed_demo_data()
    logger.info("DAWA_STARTUP: demo data ready (razia-bibi)")
    yield
    logger.info("DAWA_SHUTDOWN: goodbye")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DAWA P1",
    description=(
        "Uplift AI phone call integration — Urdu medication reminders for Pakistan. "
        "P0-A conformance preserved; P1 adds VMR, demo-call, and dose event tracking."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# P0-A routes — unchanged
app.include_router(test_call_router)

# P1 routes
app.include_router(dawa_router)


@app.get("/health")
async def health() -> dict:
    """
    Liveness probe.

    Always returns 200 when the process is up.
    Does not depend on Uplift connectivity or UPLIFT_ASSISTANT_ID being set.

    P0-A CONFORMANCE: returns exactly {"status": "ok", "service": "dawa-p0"}.
    Adding keys here breaks conformance tests.
    """
    return {"status": "ok", "service": "dawa-p0"}
