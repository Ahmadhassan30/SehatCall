"""
DAWA Voice V2 conversation-hardening tests.

Covers the four observed real-call failures:
  1. The assistant hallucinated medication facts (no closed-world rule)
  2. It was cut off mid-sentence (no short-turn policy)
  3. It then went silent (recovery from truncation undefined)
  4. It looped the opening question instead of answering the patient

ALL Uplift HTTP requests are mocked — no real call is ever placed and no real
assistant is ever created by this suite.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import seed_test_patient


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_db():
    """Init + seed the DAWA DB for context-building tests."""
    from app.services.dawa_store import init_dawa_db
    init_dawa_db()
    seed_test_patient()


@pytest.fixture
def base_prompt():
    from app.services.uplift import build_base_prompt_v2
    return build_base_prompt_v2()


@pytest.fixture
def metformin_ctx(seeded_db):
    from app.services.call_context import build_call_context
    return build_call_context("razia-bibi", "metformin-500")


def _mock_assistant_http(body: dict | None = None):
    """Mock httpx.AsyncClient for a successful assistant-creation POST."""
    resp = MagicMock()
    resp.status_code = 200
    resp.is_success = True
    resp.json.return_value = body or {"realtimeAssistantId": "asst-v2-mock"}
    resp.text = json.dumps(body or {"realtimeAssistantId": "asst-v2-mock"})

    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    holder = MagicMock(return_value=ctx)
    return holder, client


async def _create(profile: str):
    """Create an assistant against mocked HTTP; returns the captured payload."""
    from app.services import uplift as svc
    holder, client = _mock_assistant_http()
    with patch.object(svc.httpx, "AsyncClient", holder):
        with patch.object(svc.settings, "upliftai_api_key", "test-key"):
            await svc.create_assistant(profile=profile)
    return client.post.call_args.kwargs["json"]


# ---------------------------------------------------------------------------
# 1–10  V2 base prompt — anti-hallucination, short turns, anti-loop
# ---------------------------------------------------------------------------

def test_01_base_prompt_declares_closed_world(base_prompt):
    """The root hallucination cause was the absence of any closed-world rule."""
    assert "CLOSED WORLD" in base_prompt
    assert "VERIFIED FACTS" in base_prompt


def test_02_base_prompt_forbids_inventing_facts(base_prompt):
    low = base_prompt.lower()
    for verb in ("infer", "invent", "assume", "generalize"):
        assert verb in low, f"prompt must forbid '{verb}'"


def test_03_base_prompt_forbids_general_medical_knowledge(base_prompt):
    assert "general medical knowledge" in base_prompt.lower()


def test_04_base_prompt_has_urdu_refusal_for_absent_facts(base_prompt):
    """Unverified facts must trigger a refusal, not a guess."""
    assert "تصدیق شدہ معلومات نہیں" in base_prompt
    assert "کیئرگیور" in base_prompt


def test_05_base_prompt_enforces_short_turns(base_prompt):
    """Cut-offs came from unbounded turn length — need an explicit word budget."""
    assert "ONE short sentence" in base_prompt
    assert "5-15" in base_prompt


def test_06_base_prompt_requires_stop_and_wait(base_prompt):
    """After being cut off the assistant went silent; it must yield the turn cleanly."""
    assert "STOP SPEAKING and wait" in base_prompt


def test_07_base_prompt_forbids_monologue(base_prompt):
    low = base_prompt.lower()
    assert "never speak a paragraph" in low
    assert "never monologue" in low


def test_08_base_prompt_forbids_returning_to_opening(base_prompt):
    """The observed loop: it reset to the opening question after every turn."""
    assert "Do NOT return to the opening reminder" in base_prompt
    assert "Never restart the greeting mid-call" in base_prompt


def test_09_base_prompt_requires_answering_current_question(base_prompt):
    assert "Answer the patient's CURRENT question" in base_prompt
    assert "follow their branch" in base_prompt.lower()


def test_10_base_prompt_forbids_repetition(base_prompt):
    assert "Never repeat yourself" in base_prompt


# ---------------------------------------------------------------------------
# 11–14  V2 base prompt — safety and genericity
# ---------------------------------------------------------------------------

def test_11_base_prompt_forbids_diagnosis_and_dose_change(base_prompt):
    low = base_prompt.lower()
    assert "never diagnose" in low
    assert "change a dose" in low


def test_12_base_prompt_forbids_claiming_unpersisted_actions(base_prompt):
    """The backend does not persist mid-call state — the agent must not claim it does."""
    assert "recorded" in base_prompt and "you cannot" in base_prompt


def test_13_base_prompt_is_generic_no_hardcoded_truth(base_prompt):
    """Medical truth belongs in per-call context, never baked into the assistant."""
    for leaked in ("Metformin", "Amlodipine", "Razia", "raat wali goli", "500 mg"):
        assert leaked not in base_prompt, f"base prompt must not hardcode {leaked!r}"


def test_14_base_prompt_handles_ambiguous_cues(base_prompt):
    assert "AMBIGUOUS" in base_prompt
    assert "Never guess medication identity" in base_prompt


def test_15_base_prompt_separates_resolving_from_describing(base_prompt):
    """Resolving an unknown medicine != describing the already-verified due one."""
    assert "UNKNOWN medicine" in base_prompt
    assert "ALREADY-VERIFIED due medicine" in base_prompt


# ---------------------------------------------------------------------------
# 16–17  Greeting
# ---------------------------------------------------------------------------

def test_16_greeting_does_not_ask_if_taken():
    """The hardcoded 'have you taken your medicine?' greeting drove the loop."""
    from app.services.uplift import _GREETING_INSTRUCTIONS_V2 as g
    assert "یہ مت پوچھیں کہ دوائی لی یا نہیں" in g
    assert "ایک جملے سے زیادہ نہ بولیں" in g


def test_17_greeting_has_no_hardcoded_medication():
    from app.services.uplift import _GREETING_INSTRUCTIONS_V2 as g
    for leaked in ("Metformin", "Amlodipine", "Razia"):
        assert leaked not in g


# ---------------------------------------------------------------------------
# 18–24  Per-call context
# ---------------------------------------------------------------------------

def test_18_context_has_closed_world_header(metformin_ctx):
    assert metformin_ctx.additional_instructions.startswith("VERIFIED FACTS")
    assert "closed world" in metformin_ctx.additional_instructions


def test_19_context_marks_shared_cues_ambiguous(metformin_ctx):
    """White packaging is shared by both medicines — it must never identify one."""
    instr = metformin_ctx.additional_instructions
    assert "package_color=white alone -> AMBIGUOUS" in instr
    assert "tablet_shape=round alone -> AMBIGUOUS" in instr


def test_20_context_maps_stripe_colours_to_medications(metformin_ctx):
    """Blue is the current medicine; red is explicitly a different one."""
    instr = metformin_ctx.additional_instructions
    assert "stripe_color=blue -> raat wali goli (CURRENT medication)" in instr
    assert "stripe_color=red -> BP wali goli (DIFFERENT medication)" in instr


def test_21_context_supplies_discriminator_question(metformin_ctx):
    """An ambiguous cue must prompt the verified narrowing question, not a guess."""
    instr = metformin_ctx.additional_instructions
    assert "ask the stripe_color question" in instr
    assert "«blue یا red؟»" in instr
    assert "Never offer a value not listed above" in instr


def test_22_context_keeps_verified_identification_of_current_med(metformin_ctx):
    """Describing the already-verified due medicine stays allowed."""
    instr = metformin_ctx.additional_instructions
    assert "VERIFIED IDENTIFICATION (of the current medication only)" in instr
    assert "stripe_color: blue" in instr
    assert "package_color: white" in instr


def test_23_context_safety_rules_present(metformin_ctx):
    instr = metformin_ctx.additional_instructions
    assert "dose-change claim" in instr
    assert "never recommend another dose" in instr
    assert "fact absent above -> say no verified information" in instr


def test_24_context_opening_is_one_sentence_and_not_a_loop(metformin_ctx):
    instr = metformin_ctx.additional_instructions
    assert "One short Urdu sentence" in instr
    assert "Do not ask whether it was taken" in instr
    assert "Do not repeat the opening later" in instr


def test_25_context_stays_within_uplift_limits(metformin_ctx):
    """Compaction must not regress the documented Uplift size limits."""
    assert len(metformin_ctx.additional_instructions) <= 2000
    assert len(json.dumps(metformin_ctx.variables, ensure_ascii=False)) <= 3000


def test_26_amlodipine_context_flips_current_medication(seeded_db):
    """The CURRENT/DIFFERENT tags must follow the medication actually being called."""
    from app.services.call_context import build_call_context
    ctx = build_call_context("razia-bibi", "amlodipine-5")
    instr = ctx.additional_instructions
    assert "stripe_color=red -> BP wali goli (CURRENT medication)" in instr
    assert "stripe_color=blue -> raat wali goli (DIFFERENT medication)" in instr


# ---------------------------------------------------------------------------
# 27–32  V2 model stack / profiles
# ---------------------------------------------------------------------------

def test_27_voice_v2_profile_uses_groq_whisper_stt():
    from app.services.uplift import ASSISTANT_PROFILES
    stt = ASSISTANT_PROFILES["voice-v2"]["stt"]
    assert stt == {"provider": "groq", "model": "whisper-large-v3", "language": "ur"}


def test_28_voice_v2_profile_uses_groq_llm():
    from app.services.uplift import ASSISTANT_PROFILES
    llm = ASSISTANT_PROFILES["voice-v2"]["llm"]
    assert llm == {"provider": "groq", "model": "openai/gpt-oss-120b"}


def test_29_voice_v2_tts_unchanged_from_production():
    """TTS is known-good on real Pakistani telephony — it must not change."""
    from app.services.uplift import ASSISTANT_PROFILES
    assert (
        ASSISTANT_PROFILES["voice-v2"]["tts"]
        == ASSISTANT_PROFILES["hackathon"]["tts"]
        == {"provider": "upliftai", "voiceId": "helpdesk-agent",
            "outputFormat": "MP3_22050_32"}
    )


def test_30_voice_v2_sets_session_ttl():
    from app.services.uplift import ASSISTANT_PROFILES
    assert ASSISTANT_PROFILES["voice-v2"]["sessionTtlSec"] == 600


def test_31_unknown_profile_is_rejected():
    """A typo must fail loudly rather than silently creating a wrong assistant."""
    import asyncio
    from app.services.uplift import create_assistant
    with pytest.raises(ValueError, match="Unknown profile"):
        asyncio.run(create_assistant(profile="voice-v3"))


@pytest.mark.asyncio
async def test_32_voice_v2_payload_shape_is_correct():
    """config must stay a dict (the earlier 400) and carry the V2 stack + TTL."""
    payload = await _create("voice-v2")
    assert payload["name"] == "DAWA Voice V2"
    cfg = payload["config"]
    assert isinstance(cfg, dict)
    assert cfg["stt"]["default"]["model"] == "whisper-large-v3"
    assert cfg["llm"]["default"]["model"] == "openai/gpt-oss-120b"
    assert cfg["tts"]["default"]["provider"] == "upliftai"
    assert cfg["sessionTtlSec"] == 600
    assert "CLOSED WORLD" in cfg["agent"]["instructions"]


# ---------------------------------------------------------------------------
# 34–36  Multi-medication resolution (3+ medications)
# ---------------------------------------------------------------------------

@pytest.fixture
def three_medications(seeded_db):
    """Add a third white-boxed medicine with a GREEN stripe."""
    from app.services import dawa_store
    with dawa_store._connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO medications
               (id, patient_id, clinical_name, dosage, dose_instruction,
                food_instruction, schedule_time, routine_anchor, nickname)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("atorva-10", "razia-bibi", "Atorvastatin", "10 mg", "1 tablet",
             "none", "22:00", "night", "cholesterol wali goli"),
        )
        for key, val in (
            ("package_color", "white"), ("stripe_color", "green"),
            ("tablet_shape", "round"), ("storage_location", "bedside drawer"),
        ):
            conn.execute(
                """INSERT OR IGNORE INTO medication_cues
                   (medication_id, cue_key, cue_value) VALUES (?, ?, ?)""",
                ("atorva-10", key, val),
            )
    yield
    with dawa_store._connect() as conn:
        conn.execute("DELETE FROM medication_cues WHERE medication_id = 'atorva-10'")
        conn.execute("DELETE FROM medications WHERE id = 'atorva-10'")


def test_34_discriminator_question_offers_every_value(three_medications):
    """With 3 medicines the question must offer all three, never just the first two."""
    from app.services.call_context import build_call_context
    instr = build_call_context("razia-bibi", "metformin-500").additional_instructions
    # Values are emitted in deterministic alphabetical order: blue, green, red
    assert "«blue یا green یا red؟»" in instr, (
        "offering only two of three verified values would exclude a real medication"
    )


def test_35_third_medication_tagged_different(three_medications):
    from app.services.call_context import build_call_context
    instr = build_call_context("razia-bibi", "metformin-500").additional_instructions
    assert "stripe_color=green -> cholesterol wali goli (DIFFERENT medication)" in instr
    assert "stripe_color=blue -> raat wali goli (CURRENT medication)" in instr


def test_36_shared_cues_still_ambiguous_with_three_medications(three_medications):
    """All three share white/round/bedside drawer — none may identify a medicine."""
    from app.services.call_context import build_call_context
    ctx = build_call_context("razia-bibi", "metformin-500")
    instr = ctx.additional_instructions
    assert "package_color=white alone -> AMBIGUOUS" in instr
    assert "storage_location=bedside drawer alone -> AMBIGUOUS" in instr
    assert len(instr) <= 2000
    assert len(json.dumps(ctx.variables, ensure_ascii=False)) <= 3000


def test_37_single_medication_patient_has_no_false_ambiguity(seeded_db):
    """A lone medication must not be described as ambiguous."""
    from app.services.call_context import _find_ambiguous_cues
    from app.services import dawa_store
    with dawa_store._connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO patients
               (id, name, preferred_address, language, literacy_mode)
               VALUES ('solo-patient','Solo','Baba','ur','voice_first')"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO medications
               (id, patient_id, clinical_name, dosage, dose_instruction,
                food_instruction, schedule_time, routine_anchor, nickname)
               VALUES ('solo-med','solo-patient','Aspirin','75 mg','1 tablet',
                       'none','09:00','morning','subah wali goli')"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO medication_cues
               (medication_id, cue_key, cue_value)
               VALUES ('solo-med','package_color','white')"""
        )
    assert _find_ambiguous_cues("solo-patient") == {}


@pytest.mark.asyncio
async def test_33_hackathon_profile_is_unchanged():
    """Creating V2 must not alter the existing production profile."""
    payload = await _create("hackathon")
    cfg = payload["config"]
    assert payload["name"] == "DAWA Urdu Medication Reminder"
    assert cfg["stt"]["default"]["provider"] == "soniox"
    assert cfg["llm"]["default"]["model"] == "gemini-2.5-flash"
    assert "sessionTtlSec" not in cfg
