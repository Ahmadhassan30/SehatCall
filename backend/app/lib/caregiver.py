"""
Trusted caregiver identity extraction for DAWA FastAPI routes.

The TypeScript API Server (Express/Better Auth) authenticates every request
and injects two server-authoritative headers before forwarding to FastAPI:

    X-DAWA-CAREGIVER-ID      — Better Auth user.id
    X-DAWA-INTERNAL-SECRET   — shared DAWA_INTERNAL_API_SECRET env var

FastAPI NEVER calls Google or Better Auth directly.
It trusts these headers ONLY after verifying the internal secret with a
timing-safe comparison, preventing both spoofing and timing-oracle attacks.

Usage:
    @router.get("/patient")
    async def get_patient(caregiver_id: str = Depends(get_current_caregiver_id)):
        ...

The scheduler runs in-process with no HTTP context and MUST NOT use this
dependency — it accesses dawa_store directly with a known patient_id.
"""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request


def get_current_caregiver_id(request: Request) -> str:
    """
    FastAPI dependency — extract and verify the server-injected caregiver identity.

    Raises HTTP 401 if:
      - DAWA_INTERNAL_API_SECRET is not configured server-side (config error)
      - X-DAWA-INTERNAL-SECRET header is missing or does not match
      - X-DAWA-CAREGIVER-ID header is absent or empty after the secret check passes
    """
    internal_secret = os.environ.get("DAWA_INTERNAL_API_SECRET", "")
    if not internal_secret:
        # Fail closed: the secret must be present in the environment.
        # This is a server configuration problem, not a client auth problem.
        raise HTTPException(
            status_code=500,
            detail="Internal auth is not configured. Set DAWA_INTERNAL_API_SECRET.",
        )

    provided = request.headers.get("x-dawa-internal-secret", "")

    # Timing-safe comparison — prevents oracle attacks even when the secret
    # is very short.
    if not hmac.compare_digest(
        internal_secret.encode("utf-8"),
        provided.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="Unauthorized.")

    caregiver_id = request.headers.get("x-dawa-caregiver-id", "").strip()
    if not caregiver_id:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    return caregiver_id
