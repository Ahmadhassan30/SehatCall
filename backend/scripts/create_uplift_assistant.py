#!/usr/bin/env python3
"""
DAWA P0-B bootstrap script — create the Uplift Urdu medication-reminder assistant.

Run ONCE to create and validate the assistant. Do NOT run on every server start.
Does NOT place a call.

Usage:
    cd backend
    python scripts/create_uplift_assistant.py [--profile hackathon|voice-v2]
                                              [--medication "دوائی کا نام"]

Profiles:
    hackathon            — original stack: Soniox stt-rt-v4 + Gemini 2.5 Flash,
                           medication-specific legacy prompt.
    voice-v2 (default)   — DAWA Voice V2: Groq whisper-large-v3 (ur) STT +
                           Groq openai/gpt-oss-120b LLM + UpliftAI TTS
                           (helpdesk-agent, unchanged), 600s session TTL,
                           generic closed-world short-turn base prompt.

Creating a V2 assistant does NOT modify the existing production assistant —
it creates a separate assistant with its own new realtimeAssistantId.

Required environment variable:
    UPLIFTAI_API_KEY   — your Uplift API key (set in Replit Secrets)

Optional (not needed for this script):
    UPLIFT_ASSISTANT_ID — not required; this script creates the assistant
    TEST_PHONE_NUMBER   — not required; this script does not place calls
"""

from __future__ import annotations

import argparse
import asyncio
import sys

# Ensure app package is importable when run from backend/
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main(medication_name: str, profile: str) -> None:
    # Import after path adjustment
    from app.services.uplift import (  # noqa: PLC0415
        ASSISTANT_PROFILES,
        assistant_configuration_issues,
        create_assistant,
        get_assistant_configuration,
    )

    spec = ASSISTANT_PROFILES[profile]

    print("=" * 60)
    print("SehatCall - Create Uplift Urdu Medication-Reminder Assistant")
    print("=" * 60)
    print()
    print(f"Profile : {profile}")
    print(f"Name    : {spec['name']}")
    print(f"STT     : {spec['stt']['provider']} / {spec['stt']['model']} ({spec['stt']['language']})")
    print(f"LLM     : {spec['llm']['provider']} / {spec['llm']['model']}")
    print(f"TTS     : {spec['tts']['provider']} / {spec['tts']['voiceId']}")
    if spec.get("sessionTtlSec"):
        print(f"TTL     : {spec['sessionTtlSec']}s")
    if profile == "hackathon":
        print(f"Medication (default for assistant): {medication_name}")
    else:
        print("Base prompt: generic (medication truth supplied per-call)")
    print()
    print("Calling Uplift Singapore endpoint to create assistant…")
    print()

    try:
        result = await create_assistant(
            medication_name=medication_name,
            profile=profile,
        )
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Assistant creation failed.\n{exc}", file=sys.stderr)
        sys.exit(1)

    assistant_id = result.get("realtimeAssistantId")
    if not assistant_id:
        print(
            "ERROR: Unexpected response - realtimeAssistantId not found.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Validating the persisted Uplift configuration...")
    try:
        persisted = await get_assistant_configuration(str(assistant_id))
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Assistant validation failed.\n{exc}", file=sys.stderr)
        sys.exit(1)

    issues = assistant_configuration_issues(persisted)
    if issues:
        print(
            "ERROR: Uplift persisted an incomplete assistant. Missing: "
            + ", ".join(issues),
            file=sys.stderr,
        )
        sys.exit(1)

    print("Assistant created and validated successfully.")
    print()
    print(f"  realtimeAssistantId: {assistant_id}")
    print()
    print("=" * 60)
    print("NEXT STEP - Save this ID in the repository root .env.local file:")
    print()
    print("  Key  : UPLIFT_ASSISTANT_ID")
    print(f"  Value: {assistant_id}")
    print()
    print("Then restart the local FastAPI backend so it picks up the new value.")
    print("=" * 60)
    print()
    print("NOTE: The assistant instructions will be updated automatically with the")
    print("specific medication name each time POST /api/test-call is called.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create the SehatCall Uplift Urdu assistant.")
    parser.add_argument(
        "--profile",
        default="voice-v2",
        choices=["hackathon", "voice-v2"],
        help="Assistant profile to create. 'voice-v2' uses the Groq stack and the "
             "hardened closed-world prompt. Default: voice-v2",
    )
    parser.add_argument(
        "--medication",
        default="آپ کی دوائی",
        help="Default medication name to embed in instructions (hackathon profile "
             "only; ignored by voice-v2). Default: 'آپ کی دوائی'",
    )
    args = parser.parse_args()
    asyncio.run(main(medication_name=args.medication, profile=args.profile))
