"""
Uplift AI service layer for DAWA.

All HTTP communication with the Uplift API is centralised here.
No raw Uplift calls should appear in route handlers.

Singapore endpoint (ap-southeast-1) is used exclusively — this is the only
region that supports outbound calls to Pakistani phone numbers.

─────────────────────────────────────────────
P0-A CANONICAL FUNCTIONS (used by test_call.py)
─────────────────────────────────────────────
  dispatch_call()   — place one call using UPLIFT_ASSISTANT_ID from settings
  get_call_status() — fetch recent sessions from Uplift (no SQLite merge)

─────────────────────────────────────────────
FUTURE-PHASE HELPERS (preserved, not called by P0-A paths)
─────────────────────────────────────────────
  create_assistant()                    — bootstrap script only
  get_or_create_medication_assistant()  — P0-B per-medication caching
  update_assistant_instructions()       — P0-B shared-assistant PATCH path
  get_call_log()                        — used by future_calls.GET /api/call-log
  _append_call_log()                    — used by future-phase dispatch
  _build_instructions()                 — used by create_assistant
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import UPLIFT_BASE_URL, settings
from app.services.voice_catalog import (
    PREVIEW_OUTPUT_FORMAT,
    PREVIEW_PHRASE,
    is_valid_voice,
)

logger = logging.getLogger("dawa.uplift")


class IncompleteAssistantConfiguration(HTTPException):
    """Raised when a remote assistant lost required Voice V2 sections."""

    dawa_code = "UPLIFT_ASSISTANT_INCOMPLETE"

    def __init__(self, issues: list[str]):
        super().__init__(
            status_code=502,
            detail=(
                "Uplift assistant is incomplete and cannot be updated safely. "
                f"Missing: {', '.join(issues)}."
            ),
        )


# ---------------------------------------------------------------------------
# Phone number masking helper
# ---------------------------------------------------------------------------

def _mask_phone(number: str) -> str:
    """Mask a phone number for safe logging, e.g. +92XXXXXXX4567."""
    if len(number) <= 6:
        return "***"
    return number[:3] + "*" * (len(number) - 6) + number[-4:]


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------

def _auth_headers() -> dict[str, str]:
    """Return the Authorization + Content-Type headers required by Uplift."""
    return {
        "Authorization": f"Bearer {settings.upliftai_api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Error normalisation
# ---------------------------------------------------------------------------

def _raise_for_uplift_error(response: httpx.Response) -> None:
    """Translate Uplift HTTP error codes into descriptive FastAPI HTTPExceptions."""
    if response.is_success:
        return

    status = response.status_code
    try:
        body = response.json()
        uplift_message = body.get("message") or body.get("error") or str(body)
    except Exception:
        uplift_message = response.text or "(no body)"

    logger.warning(
        "UPLIFT_API_ERROR status=%s message=%s",
        status,
        uplift_message[:500],
    )

    error_map: dict[int, tuple[int, str]] = {
        400: (400, f"Uplift rejected the request (invalid request/number): {uplift_message}"),
        401: (401, "Uplift API key is invalid or missing."),
        402: (402, "Uplift account has insufficient credits to place a call."),
        404: (404, f"Uplift resource not found (check UPLIFT_ASSISTANT_ID): {uplift_message}"),
        429: (429, f"Uplift rate or concurrency limit reached: {uplift_message}"),
        500: (502, f"Uplift infrastructure error: {uplift_message}"),
    }

    if status == 409:
        detail = f"Uplift conflict (number busy or duplicate call in flight): {uplift_message}"
        raise HTTPException(status_code=409, detail=detail)

    http_status, detail = error_map.get(status, (502, f"Unexpected Uplift error {status}: {uplift_message}"))
    raise HTTPException(status_code=http_status, detail=detail)


# ---------------------------------------------------------------------------
# ── P0-A CANONICAL: Outbound call dispatch ──────────────────────────────────
# ---------------------------------------------------------------------------

async def dispatch_call() -> dict[str, Any]:
    """
    Place a real outbound Urdu medication-reminder call to TEST_PHONE_NUMBER.

    P0-A canonical path:
      1. Validate UPLIFT_ASSISTANT_ID — 503 if absent.
      2. Validate TEST_PHONE_NUMBER   — 503 if absent.
      3. Generate Idempotency-Key.
      4. POST to Uplift /calls with the configured assistant ID.
      5. Return {"callId": str, "status": "dispatched"}.

    This function:
      - NEVER creates an assistant dynamically.
      - NEVER inspects or accepts a medication name.
      - NEVER writes to SQLite.
      - NEVER writes adherence data.
    """
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured. "
                "Run scripts/create_uplift_assistant.py first, then set the "
                "returned realtimeAssistantId as UPLIFT_ASSISTANT_ID in Replit Secrets."
            ),
        )

    if not settings.test_phone_number:
        raise HTTPException(
            status_code=503,
            detail=(
                "TEST_PHONE_NUMBER is not configured. "
                "Add your Pakistani test phone number to Replit Secrets as TEST_PHONE_NUMBER."
            ),
        )

    idempotency_key = str(uuid.uuid4())
    masked = _mask_phone(settings.test_phone_number)
    logger.info(
        "UPLIFT_CALL_REQUESTED",
        extra={
            "assistantId": settings.uplift_assistant_id,
            "to": masked,
            "idempotencyKey": idempotency_key,
        },
    )

    payload = {
        "assistantId": settings.uplift_assistant_id,
        "to": settings.test_phone_number,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{UPLIFT_BASE_URL}/calls",
            json=payload,
            headers={
                **_auth_headers(),
                "Idempotency-Key": idempotency_key,
            },
        )

    _raise_for_uplift_error(response)
    data = response.json()

    call_id = data.get("callId") or data.get("id") or data.get("sessionId") or "unknown"
    logger.info("UPLIFT_CALL_DISPATCHED", extra={"callId": call_id, "to": masked})

    return {"callId": call_id, "status": "dispatched"}


# ---------------------------------------------------------------------------
# ── P0-A CANONICAL: Call / session status ───────────────────────────────────
# ---------------------------------------------------------------------------

async def get_call_status(limit: int = 10) -> list[dict[str, Any]]:
    """
    Retrieve recent Uplift session states for the configured assistant.

    P0-A canonical path: queries Uplift directly; no SQLite merge.
    Raises 503 if UPLIFT_ASSISTANT_ID is not configured.
    """
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured. "
                "Complete the assistant bootstrap step before checking call status."
            ),
        )

    logger.info(
        "UPLIFT_CALL_STATUS_CHECKED",
        extra={"assistantId": settings.uplift_assistant_id, "limit": limit},
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{UPLIFT_BASE_URL}/realtime-assistants/{settings.uplift_assistant_id}/sessions",
            params={"limit": limit},
            headers=_auth_headers(),
        )

    _raise_for_uplift_error(response)
    data = response.json()
    raw_sessions: list[dict] = data if isinstance(data, list) else data.get("sessions", [])
    return [_normalise_session(s) for s in raw_sessions]


def _normalise_session(session: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise a raw Uplift session object to the canonical DAWA shape.

    Authoritative real Uplift response fields (Singapore endpoint):
      state        — lifecycle string: dispatched|dialing|ringing|answered|completed|failed
      sessionId    — session identifier
      ringingAt    — ISO timestamp when ringing started (null if not yet reached)
      connectedAt  — ISO timestamp when connected
      answeredAt   — ISO timestamp when patient answered
      endedAt      — ISO timestamp when call ended
      createdAt    — ISO timestamp when session was created
      connected    — bool
      durationSec  — integer seconds (present after end)
      toNumber     — destination phone (masked before returning)
      fromNumber   — caller ID (masked before returning)

    Boolean lifecycle flags are derived from `state` (primary) plus
    timestamp presence as a fallback for milestone booleans:
      ringing  = state=="ringing"  OR ringingAt is present
      answered = state=="answered" OR answeredAt is present

    callId is included only if it genuinely exists in the response;
    it is NOT manufactured from sessionId.
    """
    state = session.get("state") or ""

    # Mask phone numbers — full numbers must never leave the backend
    to_raw = session.get("toNumber") or ""
    from_raw = session.get("fromNumber") or ""

    return {
        "sessionId":     session.get("sessionId") or session.get("id"),
        "callId":        session.get("callId") or None,   # only if genuinely present
        "status":        state,
        "dispatched":    state == "dispatched",
        "dialing":       state == "dialing",
        "ringing":       state == "ringing" or bool(session.get("ringingAt")),
        "answered":      state == "answered" or bool(session.get("answeredAt")),
        "completed":     state == "completed",
        "failed":        state == "failed",
        "failureReason": session.get("failureReason"),
        "connected":     session.get("connected"),
        "startedAt":     session.get("createdAt"),
        "ringingAt":     session.get("ringingAt"),
        "answeredAt":    session.get("answeredAt"),
        "endedAt":       session.get("endedAt"),
        "durationSec":   session.get("durationSec"),
        "toNumber":      _mask_phone(to_raw) if to_raw else None,
        "fromNumber":    _mask_phone(from_raw) if from_raw else None,
    }


# ---------------------------------------------------------------------------
# ── FUTURE-PHASE HELPERS ─────────────────────────────────────────────────────
# These functions are NOT called by any P0-A code path.  They are preserved
# here for use by future phases (P0-B, P1, etc.) and for the bootstrap script.
# ---------------------------------------------------------------------------

def get_call_log() -> list[dict]:
    """Return persisted call log from SQLite, most-recent first. (Future-phase.)"""
    from app.services.call_store import get_all_calls  # lazy — not loaded in P0-A
    return get_all_calls(limit=50)


def _append_call_log(log_id: str, call_id: str, medication: str, phone_masked: str = "") -> None:
    """Append a call record to SQLite. (Future-phase.)"""
    from app.services.call_store import append_call  # lazy — not loaded in P0-A
    append_call(log_id=log_id, call_id=call_id, medication=medication, phone_masked=phone_masked)


def _build_instructions(medication_name: str) -> str:
    """
    Build medication-aware Urdu instructions for the Uplift realtime assistant.
    Used by the bootstrap script and future per-medication assistant creation.
    """
    return (
        "آپ DAWA کے ایک مددگار اسسٹنٹ ہیں جو مریضوں کو ادویات یاد دلاتے ہیں۔ "
        "صرف اردو میں بات کریں۔ "
        "پہلے مریض کو سلام کریں اور پوچھیں کہ وہ کیسے ہیں۔ "
        f"پھر پوچھیں: 'کیا آپ نے آج اپنی دوائی {medication_name} لی ہے؟' "
        "اگر مریض 'ہاں' کہیں تو خوشی سے تصدیق کریں اور کہیں 'بہت اچھا، شکریہ'۔ "
        "اگر مریض 'نہیں' کہیں تو صرف شکریہ کہیں اور تجویز کریں کہ وہ اپنے ڈاکٹر سے رابطہ کریں۔ "
        "صرف دوائی لینے کی تصدیق کریں — خوراک، ضمنی اثرات یا طبی معلومات پر بالکل بات نہ کریں۔ "
        "گفتگو مختصر اور قدرتی رکھیں۔ "
        "اندرونی تفصیلات ظاہر نہ کریں۔"
    )


def build_base_prompt_v2() -> str:
    """
    DAWA Voice V2 base assistant prompt.

    Deliberately GENERIC — contains no patient name, no medication name, and no
    clinical facts.  All medical truth arrives per-call via additionalInstructions
    (see call_context.build_call_context).  This prevents the persistent assistant
    from competing with, or overriding, per-call verified facts.

    Rule scaffolding is in English (the LLM follows it more reliably) while every
    patient-facing utterance is specified in Urdu.
    """
    return (
        "You are DAWA, an Urdu-first medication companion for an elderly, "
        "low-literacy Pakistani patient.\n"
        "\n"
        "LANGUAGE\n"
        "Speak ONLY natural, simple Urdu. Never speak English to the patient.\n"
        "You are a warm conversational companion — NOT an IVR menu, NOT a medical expert.\n"
        "\n"
        "=== VOICE TURN LENGTH — HIGHEST PRIORITY ===\n"
        "Reply in ONE short sentence. At most TWO very short sentences.\n"
        "Target roughly 5-15 spoken words.\n"
        "After you answer, STOP SPEAKING and wait for the patient.\n"
        "Never speak a paragraph. Never give lists. Never monologue.\n"
        "Never repeat yourself unless the patient asks you to repeat.\n"
        "\n"
        "=== CLOSED-WORLD FACTS ===\n"
        "The VERIFIED FACTS supplied for this call are a CLOSED WORLD.\n"
        "If something is not explicitly present in VERIFIED FACTS, you do NOT know it.\n"
        "Never infer, invent, complete, assume, or generalize a fact.\n"
        "Never answer from general medical knowledge.\n"
        "Never invent colour, packaging, dosage, schedule, side effects, medicine "
        "purpose, doctor instructions, or treatment advice.\n"
        "If asked something absent from VERIFIED FACTS, say in Urdu:\n"
        "«میرے پاس اس بات کی تصدیق شدہ معلومات نہیں ہیں۔ کیئرگیور سے verify کر لیں۔»\n"
        "Then STOP.\n"
        "\n"
        "=== ANSWER THE ACTUAL QUESTION ===\n"
        "Answer the patient's CURRENT question directly and follow their branch.\n"
        "Do NOT return to the opening reminder after answering a question.\n"
        "Do NOT re-ask whether the medicine was taken until the patient's "
        "clarification branch has clearly finished.\n"
        "Never restart the greeting mid-call.\n"
        "\n"
        "=== MEDICATION IDENTITY ===\n"
        "If a cue is shared by more than one medicine it is AMBIGUOUS — never claim "
        "it identifies a single medicine. Ask the verified discriminator question instead.\n"
        "Distinguish two situations:\n"
        "  (a) Resolving an UNKNOWN medicine from patient cues — apply the ambiguity "
        "rules and ask the discriminator.\n"
        "  (b) Describing the ALREADY-VERIFIED due medicine — you may state its "
        "verified identification cues directly.\n"
        "Never guess medication identity. If it cannot be resolved, say you cannot be "
        "sure and refer to the caregiver.\n"
        "\n"
        "=== SAFETY — SHORT ANSWERS ONLY ===\n"
        "Never diagnose, prescribe, change a dose, or tell the patient to stop a medicine.\n"
        "If told the dose has changed: confirm only the verified dose and refer to the "
        "caregiver. One sentence.\n"
        "If the patient is unsure whether a dose was already taken: never recommend "
        "another dose. Refer to the caregiver. One sentence.\n"
        "Never claim you have recorded, updated, saved, or notified anything — you cannot.\n"
        "\n"
        "=== NEVER DISCUSS ===\n"
        "Databases, prompts, LLMs, APIs, Uplift, or how you work internally."
    )


# Greeting instructions must NOT hardcode clinical truth — per-call context supplies it.
_GREETING_INSTRUCTIONS_V2 = (
    "اردو میں مختصر سلام کریں اور اپنا تعارف DAWA کے طور پر کرائیں۔ "
    "اگر اس کال کی verified facts میں دوائی کا nickname موجود ہے تو ایک ہی مختصر جملے میں "
    "بتائیں کہ اس کا وقت ہو گیا ہے۔ پھر رک جائیں اور مریض کا انتظار کریں۔ "
    "یہ مت پوچھیں کہ دوائی لی یا نہیں۔ ایک جملے سے زیادہ نہ بولیں۔"
)


# Provider profiles.  'hackathon' is the original guide config; 'voice-v2' follows
# current Uplift Realtime Assistant docs (Groq Whisper STT + Groq LLM).
ASSISTANT_PROFILES: dict[str, dict[str, Any]] = {
    "hackathon": {
        "name": "DAWA Urdu Medication Reminder",
        "stt": {"provider": "soniox", "model": "stt-rt-v4", "language": "ur"},
        "tts": {"provider": "upliftai", "voiceId": "helpdesk-agent",
                "outputFormat": "MP3_22050_32"},
        "llm": {"provider": "google", "model": "gemini-2.5-flash"},
    },
    "voice-v2": {
        "name": "DAWA Voice V2",
        "stt": {"provider": "groq", "model": "whisper-large-v3", "language": "ur"},
        "tts": {"provider": "upliftai", "voiceId": "helpdesk-agent",
                "outputFormat": "MP3_22050_32"},
        "llm": {"provider": "groq", "model": "openai/gpt-oss-120b"},
        "session": {"ttl": 600},
    },
}


def assistant_configuration_issues(assistant: dict[str, Any]) -> list[str]:
    """Return missing persisted config paths without exposing prompt contents."""
    config = assistant.get("config")
    if not isinstance(config, dict):
        return ["config"]

    issues: list[str] = []
    agent = config.get("agent")
    if not isinstance(agent, dict):
        issues.append("config.agent")
    elif not agent.get("instructions"):
        issues.append("config.agent.instructions")

    for section in ("stt", "tts", "llm"):
        section_config = config.get(section)
        if not isinstance(section_config, dict) or not isinstance(
            section_config.get("default"), dict
        ):
            issues.append(f"config.{section}.default")

    return issues


async def get_assistant_configuration(assistant_id: str) -> dict[str, Any]:
    """Fetch an assistant for read-only post-bootstrap validation."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{UPLIFT_BASE_URL}/realtime-assistants/{assistant_id}",
            headers=_auth_headers(),
        )

    _raise_for_uplift_error(response)
    return response.json()


async def create_assistant(
    name: str | None = None,
    medication_name: str = "آپ کی دوائی",
    profile: str = "hackathon",
    voice_id: str | None = None,
) -> dict[str, Any]:
    """
    Create a new Uplift realtime assistant.

    profile="hackathon" — original guide stack (Soniox + Gemini), medication-specific
                          legacy prompt.  Preserved for backwards compatibility.
    profile="voice-v2"  — DAWA Voice V2: Groq Whisper STT + Groq gpt-oss-120b,
                          generic closed-world short-turn base prompt, 600s TTL.

    Called deliberately via scripts/create_uplift_assistant.py — never on startup.
    Returns the full Uplift response dict (contains realtimeAssistantId).
    """
    if profile not in ASSISTANT_PROFILES:
        raise ValueError(
            f"Unknown profile {profile!r}. Available: {sorted(ASSISTANT_PROFILES)}"
        )
    spec = ASSISTANT_PROFILES[profile]
    resolved_name = name or spec["name"]

    logger.info(
        "UPLIFT_ASSISTANT_CREATE_REQUEST name=%s profile=%s", resolved_name, profile
    )

    if profile == "voice-v2":
        agent: dict[str, Any] = {
            "instructions": build_base_prompt_v2(),
            "initialGreeting": True,
            "greetingInstructions": _GREETING_INSTRUCTIONS_V2,
            "tools": [],
        }
    else:
        agent = {
            "instructions": _build_instructions(medication_name),
            "initialGreeting": True,
            "greetingInstructions": "السلام علیکم! میں DAWA کا ادویات یاد دہانی اسسٹنٹ ہوں۔",
            "tools": [],
        }

    tts = dict(spec["tts"])
    if voice_id:
        # Bake the voice in at creation so a per-patient assistant never needs a
        # PATCH before dialling — that PATCH is what makes a shared assistant
        # race when two patients are called at the same moment.
        tts["voiceId"] = voice_id

    config: dict[str, Any] = {
        "agent": agent,
        "stt": {"default": dict(spec["stt"])},
        "tts": {"default": tts},
        "llm": {"default": dict(spec["llm"])},
    }
    if spec.get("session"):
        config["session"] = dict(spec["session"])

    payload = {
        "name": resolved_name,
        "description": "DAWA Urdu-first medication companion",
        "public": False,
        "config": config,
    }

    # Structural diagnostics — safe to log (no secrets)
    logger.info(
        "UPLIFT_ASSISTANT_PAYLOAD_SHAPE payload_type=%s config_type=%s config_keys=%s",
        type(payload).__name__,
        type(payload["config"]).__name__,
        sorted(payload["config"].keys()),
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{UPLIFT_BASE_URL}/realtime-assistants",
            json=payload,
            headers=_auth_headers(),
        )

    _raise_for_uplift_error(response)
    data = response.json()
    if "config" in data:
        issues = assistant_configuration_issues(data)
        if issues:
            logger.error(
                "UPLIFT_ASSISTANT_INCOMPLETE missing=%s",
                ",".join(issues),
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "Uplift created an incomplete assistant configuration. "
                    f"Missing: {', '.join(issues)}."
                ),
            )
    logger.info("UPLIFT_ASSISTANT_CREATED", extra={"assistantId": data.get("realtimeAssistantId")})
    return data


# ---------------------------------------------------------------------------
# Per-patient assistants
# ---------------------------------------------------------------------------

async def get_or_create_patient_assistant(patient: dict[str, Any]) -> str:
    """
    Return this patient's own Uplift assistant ID, creating it on first use.

    Why per patient: voice is a property of the assistant, not of a call. With a
    single shared assistant, honouring each patient's chosen voice means PATCHing
    that assistant immediately before dialling — so two patients called at the
    same moment race, and whoever PATCHes last decides what both of them hear.
    Giving each patient their own assistant removes the shared mutable state
    instead of trying to serialise access to it.

    The ID is cached on the patient row, so this costs one create per patient
    for the lifetime of the account, not one per call or one per restart.
    """
    from app.services import dawa_store  # noqa: PLC0415  (avoids circular import)

    existing = patient.get("assistant_id")
    if existing:
        return str(existing)

    patient_id = patient["id"]
    voice_id = patient.get("preferred_voice_id") or DEFAULT_VOICE_ID
    if not is_valid_voice(voice_id):
        voice_id = DEFAULT_VOICE_ID

    data = await create_assistant(
        name=f"DAWA — {patient.get('name') or patient_id}",
        profile="voice-v2",
        voice_id=voice_id,
    )
    assistant_id = data.get("realtimeAssistantId")
    if not assistant_id:
        raise RuntimeError(
            f"Uplift did not return a realtimeAssistantId for patient {patient_id!r}."
        )

    dawa_store.set_patient_assistant_id(patient_id, assistant_id)
    logger.info(
        "DAWA_PATIENT_ASSISTANT_CREATED patient=%s assistantId=%s voiceId=%s",
        patient_id, assistant_id, voice_id,
    )
    return str(assistant_id)


# ---------------------------------------------------------------------------
# Phone-ownership verification call
# ---------------------------------------------------------------------------

_VERIFICATION_INSTRUCTIONS = """\
VERIFICATION CALL — this is NOT a medication reminder.

Say exactly this, in Urdu, and nothing else:
"السلام علیکم۔ یہ DAWA کی تصدیقی کال ہے۔ آپ کا کوڈ ہے: {spoken}۔ دوبارہ سن لیجیے: {spoken}۔ شکریہ۔"

Rules:
- Read each digit separately, slowly, with a clear pause between digits.
- Say the code exactly twice, then end the call.
- Do NOT mention any medication. Do NOT ask any question.
- If the person speaks, repeat only the code once more, then end the call.
"""


async def dispatch_verification_call(phone_e164: str, code: str) -> str:
    """
    Ring a number and speak a verification code aloud.

    Uses the shared base assistant deliberately: a verification call happens
    before the patient is confirmed, so creating a dedicated assistant for a
    number that may never be verified would leak assistants on every typo.
    Voice preference is irrelevant here — the call only reads digits.

    Returns the Uplift call ID.
    """
    from app.services.phone_verification import mask_phone, spoken_code  # noqa: PLC0415

    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured, so DAWA cannot place the "
                "verification call. Run scripts/create_uplift_assistant.py first."
            ),
        )

    spoken = spoken_code(code)
    masked = mask_phone(phone_e164)
    instructions = _VERIFICATION_INSTRUCTIONS.format(spoken=spoken)
    payload = {
        "assistantId": settings.uplift_assistant_id,
        "to": phone_e164,
        "additionalInstructions": instructions,
    }

    logger.info(
        "DAWA_VERIFICATION_CALL_REQUESTED to=%s payloadKeys=%s instructionsChars=%d",
        masked,
        sorted(payload.keys()),
        len(instructions),
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{UPLIFT_BASE_URL}/calls",
            json=payload,
            headers={
                **_auth_headers(),
                # New key per send: a resend is a genuinely new call, and reusing
                # the key would make Uplift silently dedupe it away.
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )

    _raise_for_uplift_error(response)
    data = response.json()
    call_id = data.get("callId") or data.get("id") or data.get("sessionId") or "unknown"
    # The code itself is never logged — only that a call went out.
    logger.info("DAWA_VERIFICATION_CALL_SENT to=%s callId=%s", masked, call_id)
    return str(call_id)


# Maps medication_name -> realtimeAssistantId (future-phase in-process cache).
_medication_assistant_cache: dict[str, str] = {}


async def get_or_create_medication_assistant(medication_name: str) -> str:
    """
    Return a cached Uplift assistant ID for *medication_name*, creating one on
    first use if not already cached.  (Future-phase — not called by P0-A dispatch_call.)
    """
    if medication_name in _medication_assistant_cache:
        cached_id = _medication_assistant_cache[medication_name]
        logger.debug(
            "MEDICATION_ASSISTANT_CACHE_HIT",
            extra={"medication": medication_name, "assistantId": cached_id},
        )
        return cached_id

    logger.info("MEDICATION_ASSISTANT_CREATE_START", extra={"medication": medication_name})
    data = await create_assistant(
        name=f"DAWA Urdu - {medication_name}",
        medication_name=medication_name,
    )
    assistant_id: str | None = data.get("realtimeAssistantId")
    if not assistant_id:
        raise HTTPException(
            status_code=502,
            detail="Uplift did not return a realtimeAssistantId for the new medication assistant.",
        )

    _medication_assistant_cache[medication_name] = assistant_id
    logger.info(
        "MEDICATION_ASSISTANT_CACHED",
        extra={"medication": medication_name, "assistantId": assistant_id},
    )
    return assistant_id


async def update_assistant_instructions(medication_name: str) -> None:
    """
    PATCH the base Uplift assistant's instructions to include a specific medication name.
    (Future-phase — not called by P0-A dispatch_call.)
    """
    if not settings.uplift_assistant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "UPLIFT_ASSISTANT_ID is not configured. "
                "Run scripts/create_uplift_assistant.py first."
            ),
        )

    payload = {"instructions": _build_instructions(medication_name)}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.patch(
            f"{UPLIFT_BASE_URL}/realtime-assistants/{settings.uplift_assistant_id}",
            json=payload,
            headers=_auth_headers(),
        )

    _raise_for_uplift_error(response)
    logger.info(
        "UPLIFT_ASSISTANT_UPDATED",
        extra={"assistantId": settings.uplift_assistant_id, "medication": medication_name},
    )


# ---------------------------------------------------------------------------
# P3 — DAWA voice selection
# ---------------------------------------------------------------------------

async def update_assistant_voice(voice_id: str, assistant_id: str | None = None) -> None:
    """
    Point the existing Voice V2 assistant at a different Uplift TTS voice.

    Uplift's regional endpoint replaces ``config`` when a partial config is
    posted, despite the API documentation describing partial updates. Fetch and
    resend the complete persisted config so agent instructions, greeting, STT,
    LLM and session configuration survive a voice change.

    Raises HTTPException if Uplift rejects the update, so the caller can avoid
    persisting a voice the assistant is not actually using.
    """
    if not is_valid_voice(voice_id):
        raise HTTPException(status_code=400, detail="Unknown DAWA voice.")

    # Default to the shared base assistant so existing callers keep working;
    # per-patient callers pass their own assistant and therefore cannot change
    # what any other patient hears.
    target = assistant_id or settings.uplift_assistant_id
    if not target:
        raise HTTPException(
            status_code=503,
            detail="UPLIFT_ASSISTANT_ID is not configured.",
        )

    persisted = await get_assistant_configuration(str(target))
    issues = assistant_configuration_issues(persisted)
    if issues:
        raise IncompleteAssistantConfiguration(issues)

    config = dict(persisted["config"])
    config["tts"] = {
        "default": {
            "provider": "upliftai",
            "voiceId": voice_id,
            "outputFormat": "MP3_22050_32",
        }
    }
    payload = {"config": config}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{UPLIFT_BASE_URL}/realtime-assistants/{target}",
            json=payload,
            headers=_auth_headers(),
        )

    _raise_for_uplift_error(response)
    logger.info("DAWA_VOICE_UPDATED voiceId=%s assistantId=%s", voice_id, target)


async def synthesize_voice_preview(voice_id: str) -> bytes:
    """
    Synthesize the FIXED DAWA preview phrase in the given voice.

    The phrase is a server-side constant — caregiver-supplied text is never
    accepted here, so this endpoint cannot be used as a free TTS proxy.
    Returns raw MP3 bytes.
    """
    if not is_valid_voice(voice_id):
        raise HTTPException(status_code=400, detail="Unknown DAWA voice.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{UPLIFT_BASE_URL}/synthesis/text-to-speech",
            json={
                "voiceId": voice_id,
                "text": PREVIEW_PHRASE,
                "outputFormat": PREVIEW_OUTPUT_FORMAT,
            },
            headers=_auth_headers(),
        )

    _raise_for_uplift_error(response)
    return response.content
