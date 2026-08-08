"""
DAWA Verified Call Context Builder.

Before DAWA places a patient call, this module builds a compact verified
context from the database.  The context includes:

  - Patient name and preferred address
  - Medication nickname, clinical name, dosage, dose instruction
  - Verified visual recognition cues
  - A backend-derived medication resolution table

The context is serialised into:

  variables              — flat dict  (max ~3000 chars total as JSON)
  additional_instructions — string    (max ~2000 chars)

Both are passed directly to Uplift POST /calls.  The backend establishes
medication truth BEFORE the call; no mid-call database writes are assumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.dawa_store import (
    get_medication,
    get_medication_cues,
    get_patient,
)
from app.services.vmr import build_resolution_guide


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CallContext:
    variables: dict[str, str]
    additional_instructions: str

    def to_dict(self) -> dict:
        return {
            "variables": self.variables,
            "additionalInstructions": self.additional_instructions,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

_VARIABLES_MAX_CHARS = 3000
_INSTRUCTIONS_MAX_CHARS = 2000


def build_call_context(patient_id: str, medication_id: str) -> CallContext:
    """
    Build a verified call context for one patient + medication combination.

    Raises ValueError if patient or medication is not found in the DB.
    """
    patient = get_patient(patient_id)
    if not patient:
        raise ValueError(f"Patient not found: {patient_id!r}")

    medication = get_medication(medication_id)
    if not medication or medication["patient_id"] != patient_id:
        raise ValueError(
            f"Medication {medication_id!r} not found or does not belong to patient {patient_id!r}"
        )

    cues: dict[str, str] = get_medication_cues(medication_id)
    resolution_guide = build_resolution_guide(patient_id)

    variables = _build_variables(patient, medication, cues, resolution_guide)
    instructions = _build_instructions(patient, medication, cues, resolution_guide)

    # Guard against exceeding Uplift documented size limits
    variables_json_len = len(json.dumps(variables, ensure_ascii=False))
    if variables_json_len > _VARIABLES_MAX_CHARS:
        raise ValueError(
            f"variables JSON is {variables_json_len} chars (limit {_VARIABLES_MAX_CHARS}). "
            "Shorten cue list or resolution guide."
        )
    if len(instructions) > _INSTRUCTIONS_MAX_CHARS:
        raise ValueError(
            f"additionalInstructions is {len(instructions)} chars (limit {_INSTRUCTIONS_MAX_CHARS}). "
            "Shorten the instructions template."
        )

    return CallContext(variables=variables, additional_instructions=instructions)


# ---------------------------------------------------------------------------
# Variables builder
# ---------------------------------------------------------------------------

def _build_variables(
    patient: dict,
    medication: dict,
    cues: dict[str, str],
    resolution_guide: list[dict],
) -> dict[str, str]:
    """
    Build the flat variables dict passed to Uplift.
    All values are strings.  Total JSON must stay under _VARIABLES_MAX_CHARS.
    """
    nickname = medication.get("nickname") or medication["clinical_name"]
    cue_list = "; ".join(f"{k}={v}" for k, v in sorted(cues.items()))
    res_summary = _compact_resolution_guide(resolution_guide, medication, patient)

    return {
        "patient_name":      patient["name"],
        "preferred_address": patient["preferred_address"],
        "nickname":          nickname,
        "clinical_name":     medication["clinical_name"],
        "dosage":            medication["dosage"],
        "dose_instruction":  medication["dose_instruction"],
        "food_instruction":  medication["food_instruction"],
        "routine_anchor":    medication["routine_anchor"],
        "cue_list":          cue_list or "no verified cues available",
        "resolution_guide":  res_summary or "not available",
    }


def _compact_resolution_guide(
    guide: list[dict],
    target_medication: dict,
    patient: dict,
) -> str:
    """
    Produce a one-line resolution guide derived from VMR data.

    Example output:
      "safed dabba aur neeli patti → Metformin (raat wali goli); safed dabba aur laal patti → Amlodipine (BP wali goli)"
    """
    if not guide:
        return ""

    parts: list[str] = []
    for entry in guide:
        disc = entry["discriminator"]
        for mapping in entry["mappings"]:
            nick = mapping.get("nickname") or mapping.get("clinicalName", "")
            cname = mapping.get("clinicalName", "")
            parts.append(f"{disc}={mapping['value']} → {cname} ({nick})")

    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Additional instructions builder
# ---------------------------------------------------------------------------

def _find_ambiguous_cues(patient_id: str) -> dict[str, str]:
    """
    Derive cue key/value pairs that do NOT uniquely identify a medicine —
    i.e. every one of the patient's medications shares the same value.

    For Razia: package_color=white, tablet_shape=round, storage_location=bedside
    drawer are all shared, so none of them alone identifies a medicine.
    Derived from the DB, never hardcoded.
    """
    from app.services.dawa_store import get_all_medication_cues_for_patient

    all_cues = get_all_medication_cues_for_patient(patient_id)
    if len(all_cues) < 2:
        return {}

    keys: set[str] = set()
    for cue_map in all_cues.values():
        keys.update(cue_map.keys())

    ambiguous: dict[str, str] = {}
    for key in sorted(keys):
        values = {
            (cue_map.get(key) or "").lower()
            for cue_map in all_cues.values()
        }
        # Shared across every medication and non-empty → ambiguous on its own
        if len(values) == 1 and "" not in values:
            ambiguous[key] = values.pop()
    return ambiguous


def _build_instructions(
    patient: dict,
    medication: dict,
    cues: dict[str, str],
    resolution_guide: list[dict],
) -> str:
    """
    Build the compact DAWA Voice V2 per-call context.

    Structured facts, not prose — realtime LLMs ground far more reliably on
    short labelled key/value blocks than on paragraphs, and short context
    reduces the chance of a long hallucinated monologue.

    Max _INSTRUCTIONS_MAX_CHARS chars.
    """
    addr = patient["preferred_address"]
    name = patient["name"]
    nick = medication.get("nickname") or medication["clinical_name"]
    cname = medication["clinical_name"]
    dosage = medication["dosage"]
    dose_instr = medication["dose_instruction"]
    food_instr = medication["food_instruction"]

    # ── Verified identification of the CURRENT (already-resolved) medicine ──
    if cues:
        cue_block = "\n".join(f"{k}: {v}" for k, v in sorted(cues.items()))
    else:
        cue_block = "(none verified)"

    # ── Resolution rules ────────────────────────────────────────────────────
    res_lines: list[str] = []
    ambiguous = _find_ambiguous_cues(patient["id"])
    for key, val in ambiguous.items():
        res_lines.append(f"{key}={val} alone -> AMBIGUOUS, do not identify")

    for entry in resolution_guide:
        disc = entry["discriminator"]
        for m in entry["mappings"]:
            label = m.get("nickname") or m.get("clinicalName", "")
            is_current = m.get("medicationId") == medication["id"]
            tag = "CURRENT medication" if is_current else "DIFFERENT medication"
            res_lines.append(f"{disc}={m['value']} -> {label} ({tag})")
    res_block = "\n".join(res_lines) if res_lines else "(single medication — no ambiguity)"

    # Urdu discriminator question.  Must offer EVERY verified value of a single
    # discriminating key — offering only the first two would silently exclude a
    # real medication and push the patient toward a wrong answer.
    disc_question = ""
    if resolution_guide:
        entry = resolution_guide[0]
        vals = [m["value"] for m in entry["mappings"]]
        if len(vals) >= 2:
            choices = " یا ".join(vals)
            disc_question = (
                f"\nIf the patient gives only an ambiguous cue, ask the "
                f"{entry['discriminator']} question offering every verified value: "
                f"«{choices}؟» Never offer a value not listed above."
            )

    food_part = (
        f"\ntiming: {food_instr}"
        if food_instr and food_instr.lower() != "none"
        else ""
    )

    return (
        "VERIFIED FACTS (closed world — nothing outside this block is known)\n"
        f"patient_name: {name}\n"
        f"preferred_address: {addr}\n"
        "\n"
        "CURRENT MEDICATION (already verified as due — do not re-resolve)\n"
        f"nickname: {nick}\n"
        f"clinical_name: {cname}\n"
        f"dosage: {dosage}\n"
        f"dose: {dose_instr}"
        f"{food_part}\n"
        "\n"
        "VERIFIED IDENTIFICATION (of the current medication only)\n"
        f"{cue_block}\n"
        "\n"
        "RESOLUTION RULES (for resolving an UNKNOWN medicine from patient cues)\n"
        f"{res_block}"
        f"{disc_question}\n"
        "\n"
        "SAFETY\n"
        f"dose-change claim -> confirm only «{dose_instr}», verify with caregiver\n"
        "unsure if already taken -> never recommend another dose, refer to caregiver\n"
        "fact absent above -> say no verified information, refer to caregiver\n"
        "\n"
        "OPENING\n"
        f"One short Urdu sentence: greet as DAWA and say «{nick}» time has come. Then STOP.\n"
        "Do not ask whether it was taken. Do not repeat the opening later."
    )
