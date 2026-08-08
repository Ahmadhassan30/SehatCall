"""
Deterministic doctor-instruction conflict detection.

The caregiver may type a free-text "Doctor's Instructions" note alongside the
structured clinical fields.  Those structured fields remain authoritative — but
if the note obviously contradicts them we warn the caregiver BEFORE saving.

Design constraints (deliberate):
  - No LLM.  A language model must never adjudicate which medical value is correct.
  - No general medical NLP.  We only detect a narrow, high-confidence pattern:
    an explicit tablet/pill count in the note that differs from the structured dose.
  - Prefer silence over a false alarm.  If the note is ambiguous, we return no
    warning rather than pretending to understand it.

This produces a WARNING ONLY.  It never blocks a save and never edits data.
"""

from __future__ import annotations

import re

# Written-out numbers a caregiver realistically types, plus Roman-Urdu forms.
_WORD_NUMBERS: dict[str, int] = {
    "one": 1, "a": 1, "an": 1, "single": 1, "ek": 1,
    "two": 2, "double": 2, "do": 2,
    "three": 3, "teen": 3,
    "four": 4, "char": 4,
    "half": 0,  # deliberately unhandled — see _extract_count
}

# "2 tablets", "two tablets", "1 goli", "two pills"
_UNIT = r"(?:tablets?|pills?|capsules?|tabs?|goli(?:yan|yaan)?)"
_DIGIT_PATTERN = re.compile(rf"(\d+)\s*{_UNIT}", re.IGNORECASE)
_WORD_PATTERN = re.compile(
    rf"\b({'|'.join(k for k in _WORD_NUMBERS if k != 'half')})\s+{_UNIT}",
    re.IGNORECASE,
)


def _extract_count(text: str) -> int | None:
    """
    Extract an explicit tablet count from free text.

    Returns None when nothing unambiguous is found — including fractional doses
    ("half a tablet"), which we intentionally do not try to reason about.
    """
    if not text:
        return None
    lowered = text.lower()

    # Fractions are out of scope; stay silent rather than guess.
    if "half" in lowered or "1/2" in lowered or "¼" in lowered or "½" in lowered:
        return None

    m = _DIGIT_PATTERN.search(lowered)
    if m:
        return int(m.group(1))

    m = _WORD_PATTERN.search(lowered)
    if m:
        return _WORD_NUMBERS[m.group(1).lower()]

    return None


def detect_dose_conflict(
    dose_instruction: str | None,
    doctor_instructions: str | None,
) -> str | None:
    """
    Compare the structured dose against the free-text doctor note.

    Returns a caregiver-facing warning string, or None when there is no
    high-confidence conflict.
    """
    structured = _extract_count(dose_instruction or "")
    freetext = _extract_count(doctor_instructions or "")

    if structured is None or freetext is None:
        return None
    if structured == freetext:
        return None

    return (
        "Possible conflict with structured dose. Please verify. "
        f"Structured dose says {structured}, doctor's instructions say {freetext}."
    )


def detect_conflicts(medication: dict) -> list[str]:
    """All deterministic warnings for a medication record."""
    warnings: list[str] = []
    dose_conflict = detect_dose_conflict(
        medication.get("dose_instruction"),
        medication.get("doctor_instructions"),
    )
    if dose_conflict:
        warnings.append(dose_conflict)
    return warnings
