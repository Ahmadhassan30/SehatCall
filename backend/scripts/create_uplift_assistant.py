#!/usr/bin/env python3
"""
DAWA P0-A bootstrap script — create the Uplift Urdu test assistant.

Run ONCE to create the assistant. Do NOT run on every server start.
Does NOT place a call.

Usage:
    cd backend
    python scripts/create_uplift_assistant.py

Required environment variable:
    UPLIFTAI_API_KEY   — your Uplift API key (set in Replit Secrets)

Optional (not needed for this script):
    UPLIFT_ASSISTANT_ID — not required; this script creates the assistant
    TEST_PHONE_NUMBER   — not required; this script does not place calls
"""

from __future__ import annotations

import asyncio
import sys

# Ensure app package is importable when run from backend/
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    # Import after path adjustment
    from app.services.uplift import create_assistant  # noqa: PLC0415

    print("=" * 60)
    print("DAWA P0-A — Create Uplift Urdu Assistant")
    print("=" * 60)
    print()
    print("Calling Uplift Singapore endpoint to create assistant…")
    print()

    try:
        result = await create_assistant()
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Assistant creation failed.\n{exc}", file=sys.stderr)
        sys.exit(1)

    assistant_id = result.get("realtimeAssistantId")
    if not assistant_id:
        print(
            f"ERROR: Unexpected response — realtimeAssistantId not found.\nFull response: {result}",
            file=sys.stderr,
        )
        sys.exit(1)

    print("✓ Assistant created successfully.")
    print()
    print(f"  realtimeAssistantId: {assistant_id}")
    print()
    print("=" * 60)
    print("NEXT STEP — Save this ID as a Replit Secret:")
    print()
    print("  Key  : UPLIFT_ASSISTANT_ID")
    print(f"  Value: {assistant_id}")
    print()
    print("Then restart the FastAPI workflow so it picks up the new secret.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
