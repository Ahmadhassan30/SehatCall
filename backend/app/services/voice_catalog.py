"""
DAWA verified Uplift voice catalog.

SOURCE OF TRUTH
---------------
Every voice ID below is copied verbatim from Uplift's public documentation:

    https://docs.upliftai.org/orator_voices   ("Earlier voices" section)

Uplift's docs page also renders a larger dynamically-loaded gallery (advertised
as 82 native voices), but those IDs are injected client-side and are NOT present
in any documented, machine-readable source we can verify from the server.  There
is no documented "List Voices" REST endpoint.  Rather than scrape an
undocumented private API or invent plausible-looking IDs, DAWA exposes only the
explicitly documented subset plus the voice already proven working in production.

NOTHING IN THIS FILE IS INVENTED.
  - `id`   — verbatim documented voiceId
  - `name` — verbatim documented label
  - `language` — taken from the documented label prefix

We deliberately do NOT attach gender, age, accent, or personality descriptions
beyond what the documented label itself states.  A caregiver choosing a voice
for an elderly patient must not be shown a guessed characterisation.

To add voices later, append verified entries here.  This module is the single
authoritative source — the frontend never hardcodes voice IDs.
"""

from __future__ import annotations

from typing import Any


# The voice the working production Voice V2 assistant already uses.  Kept as the
# default so enabling voice selection does not silently change Razia's voice.
DEFAULT_VOICE_ID = "helpdesk-agent"

# Fixed Urdu preview line: "Assalam-o-Alaikum Ammi, main SehatCall hoon."
# Hardcoded server-side — caregiver text is never sent to the TTS endpoint.
PREVIEW_PHRASE = "السلام علیکم اماں، میں SehatCall ہوں۔"

# Documented output format used by the Voice V2 assistant's TTS config.
PREVIEW_OUTPUT_FORMAT = "MP3_22050_32"


_VOICES: list[dict[str, Any]] = [
    {
        "id": DEFAULT_VOICE_ID,
        "name": "SehatCall Helpdesk",
        "language": "Urdu",
        "description": "The voice SehatCall currently uses for reminder calls.",
    },
    {"id": "v_meklc281", "name": "Urdu — Info/Education V2", "language": "Urdu"},
    {"id": "v_8eelc901", "name": "Urdu — Info/Education", "language": "Urdu"},
    {"id": "v_30s70t3a", "name": "Urdu — Nostalgic News", "language": "Urdu"},
    {"id": "v_yypgzenx", "name": "Urdu — Dada Jee", "language": "Urdu"},
    {"id": "v_kwmp7zxt", "name": "Urdu — Gen Z (beta)", "language": "Urdu"},
    {"id": "v_sd0kl3m9", "name": "Sindhi — Female", "language": "Sindhi"},
    {"id": "v_sd6mn4p2", "name": "Sindhi — Male Calm", "language": "Sindhi"},
    {"id": "v_sd9qr7x5", "name": "Sindhi — Male News", "language": "Sindhi"},
    {"id": "v_bl0ab8c4", "name": "Balochi — Male", "language": "Balochi"},
    {"id": "v_bl1de2f7", "name": "Balochi — Female", "language": "Balochi"},
]


def list_voices() -> list[dict[str, Any]]:
    """
    Safe UI metadata for the caregiver app.

    Contains no API keys, no assistant ID, and no provider internals — only the
    voice id (needed to submit a selection) plus display metadata.
    """
    return [
        {
            "id": v["id"],
            "name": v["name"],
            "description": v.get("description"),
            "language": v["language"],
            "previewable": True,
        }
        for v in _VOICES
    ]


def is_valid_voice(voice_id: str) -> bool:
    """True only for voices in the verified catalog."""
    return any(v["id"] == voice_id for v in _VOICES)


def get_voice(voice_id: str) -> dict[str, Any] | None:
    for v in _VOICES:
        if v["id"] == voice_id:
            return dict(v)
    return None


def voice_name(voice_id: str | None) -> str | None:
    """Friendly display name for a voice id, or None if unknown."""
    if not voice_id:
        return None
    v = get_voice(voice_id)
    return v["name"] if v else None
