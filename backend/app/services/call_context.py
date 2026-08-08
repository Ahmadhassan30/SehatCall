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

def _build_instructions(
    patient: dict,
    medication: dict,
    cues: dict[str, str],
    resolution_guide: list[dict],
) -> str:
    """
    Build the Urdu additional_instructions string.
    Max _INSTRUCTIONS_MAX_CHARS chars.  Written in Urdu with Roman Urdu labels.
    """
    addr = patient["preferred_address"]
    name = patient["name"]
    nick = medication.get("nickname") or medication["clinical_name"]
    cname = medication["clinical_name"]
    dosage = medication["dosage"]
    dose_instr = medication["dose_instruction"]
    food_instr = medication["food_instruction"]

    # Build cue block from verified cues only
    if cues:
        cue_block = "\n".join(f"  - {k}: {v}" for k, v in sorted(cues.items()))
    else:
        cue_block = "  (کوئی تصدیق شدہ اشارے نہیں)"

    # Build resolution block from VMR guide
    if resolution_guide:
        res_lines: list[str] = []
        for entry in resolution_guide:
            disc = entry["discriminator"]
            for m in entry["mappings"]:
                label = m.get("nickname") or m.get("clinicalName", "")
                res_lines.append(f"  {disc}={m['value']} → {label}")
        res_block = "\n".join(res_lines)
    else:
        res_block = "  (ایک ہی دوائی ہے)"

    instructions = (
        f"آپ DAWA ہیں — ادویات یاد دہانی کی آواز اسسٹنٹ۔ صرف قدرتی اردو بولیں۔\n"
        f"\n"
        f"مریض: {name}، انہیں «{addr}» کہیں\n"
        f"دوائی: «{nick}» ({cname} {dosage})\n"
        f"ہدایت: {dose_instr}"
        + (f"، {food_instr}" if food_instr and food_instr.lower() != "none" else "")
        + f"\n"
        f"\n"
        f"== کال کھولیں ==\n"
        f"«السلام علیکم {addr}، میں DAWA ہوں۔ آپ کی {nick} کا وقت ہو گیا ہے۔»\n"
        f"مختصر جملے بولیں۔ مریض کو بولنے کا موقع دیں۔\n"
        f"\n"
        f"== دوائی پہچان — صرف یہ تصدیق شدہ اشارے استعمال کریں ==\n"
        f"{cue_block}\n"
        f"پہچان رہنما (VMR سے حاصل):\n"
        f"{res_block}\n"
        f"\n"
        f"== حفاظتی اصول — لازمی اور غیر مشروط ==\n"
        f"1. خوراک کبھی تبدیل نہ کریں۔\n"
        f"   اگر کہیں «ڈاکٹر نے دو گولیاں کہی ہیں»:\n"
        f"   «{addr}، میرے پاس {dose_instr} کی تصدیق ہے۔ تبدیلی کیئرگیور سے verify کروائیں۔»\n"
        f"2. دوبارہ خوراک کی سفارش نہ کریں۔\n"
        f"   اگر کہیں «یاد نہیں پہلے لی تھی یا نہیں»:\n"
        f"   «یقین نہ ہو تو دوسری گولی نہ لیں — کیئرگیور سے پوچھیں۔»\n"
        f"3. صرف تصدیق شدہ معلومات دیں — اندازہ، تشخیص، طبی مشورہ بالکل نہیں۔\n"
        f"4. اگر دوائی کا تعین نہ ہو سکے تو کہیں: «ابھی یقین سے نہیں بتا سکتی، کیئرگیور سے رابطہ کریں۔»\n"
        f"5. کال مختصر رکھیں۔ داخلی تفصیلات ظاہر نہ کریں۔"
    )

    return instructions
