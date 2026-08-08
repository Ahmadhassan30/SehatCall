"""
DAWA P0-A — FastAPI application entry point.

Registers:
  GET /health          — liveness probe, no external dependencies
  POST /api/test-call  — dispatch Urdu outbound call (requires secrets at call time)
  GET  /api/test-call/status — inspect recent Uplift sessions

The server starts successfully even when UPLIFT_ASSISTANT_ID is absent.
"""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI

from app.api.test_call import router as test_call_router
from app.config import settings
from app.services.call_store import init_db

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
# Startup configuration checks
# ---------------------------------------------------------------------------

def _check_startup_config() -> None:
    """
    Emit prominent warnings for any missing security-critical configuration.

    Called once at module load so issues are visible immediately in logs
    regardless of whether any request is ever made.
    """
    if not settings.uplift_webhook_secret:
        if settings.dawa_dev_mode:
            logger.warning(
                "⚠️  SECURITY WARNING: UPLIFT_WEBHOOK_SECRET is not set. "
                "Webhook signature verification is DISABLED because DAWA_DEV_MODE=true. "
                "Any request to /api/webhook/call-complete will be accepted without verification. "
                "Set UPLIFT_WEBHOOK_SECRET in Replit Secrets before going to production."
            )
        else:
            logger.warning(
                "⚠️  SECURITY WARNING: UPLIFT_WEBHOOK_SECRET is not set and DAWA_DEV_MODE is false. "
                "All webhook requests to /api/webhook/call-complete will be rejected with 503 "
                "until the secret is configured. "
                "Set UPLIFT_WEBHOOK_SECRET in Replit Secrets to enable webhook processing."
            )

    if not settings.dawa_admin_token:
        logger.warning(
            "⚠️  SECURITY WARNING: DAWA_ADMIN_TOKEN is not set. "
            "Admin-protected endpoints (/api/test-call, /api/call-log) will reject all requests. "
            "Set DAWA_ADMIN_TOKEN in Replit Secrets to enable those endpoints."
        )


_check_startup_config()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DAWA P0-A",
    description="Uplift AI phone call integration spike — Urdu outbound calls to Pakistan",
    version="0.1.0",
)

# Initialise persistent call store on startup (idempotent — safe to call every boot)
init_db()

app.include_router(test_call_router)


@app.get("/health")
async def health() -> dict:
    """
    Liveness probe.

    Does NOT depend on Uplift connectivity or UPLIFT_ASSISTANT_ID being set.
    Always returns 200 when the process is up.

    The response includes a 'warnings' list that surfaces any missing
    security-critical configuration so operators can spot problems without
    tailing logs.
    """
    warnings: list[str] = []

    if not settings.uplift_webhook_secret:
        if settings.dawa_dev_mode:
            warnings.append(
                "UPLIFT_WEBHOOK_SECRET is not set — webhook signature verification is "
                "DISABLED (DAWA_DEV_MODE=true). Do not use this configuration in production."
            )
        else:
            warnings.append(
                "UPLIFT_WEBHOOK_SECRET is not set — all webhook requests will be rejected "
                "with 503 until the secret is configured in Replit Secrets."
            )

    if not settings.dawa_admin_token:
        warnings.append(
            "DAWA_ADMIN_TOKEN is not set — admin endpoints are inaccessible until "
            "the token is configured in Replit Secrets."
        )

    return {
        "status": "ok",
        "service": "dawa-p0",
        "warnings": warnings,
    }
