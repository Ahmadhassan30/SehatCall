"""
DAWA P0-A — FastAPI application entry point.

Registers:
  GET /health                — liveness probe, no external dependencies
  POST /api/test-call        — dispatch Urdu outbound call (requires secrets at call time)
  GET  /api/test-call/status — inspect recent Uplift sessions

Future-phase routes (GET /api/call-log, POST /api/webhook/call-complete) live in
app/api/future_calls.py and are intentionally NOT registered here during P0-A.

The server starts successfully even when UPLIFT_ASSISTANT_ID is absent.
No database initialisation is performed at startup.
"""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI

from app.api.test_call import router as test_call_router

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
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DAWA P0-A",
    description="Uplift AI phone call integration spike — Urdu outbound calls to Pakistan",
    version="0.1.0",
)

app.include_router(test_call_router)


@app.get("/health")
async def health() -> dict:
    """
    Liveness probe.

    Always returns 200 when the process is up.
    Does not depend on Uplift connectivity or UPLIFT_ASSISTANT_ID being set.
    """
    return {"status": "ok", "service": "dawa-p0"}
