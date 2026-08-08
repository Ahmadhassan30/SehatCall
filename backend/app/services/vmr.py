"""
DAWA Verified Medication Resolution (VMR).

Deterministic.  No LLM.  No embeddings.  No fuzzy matching.  No probabilities.

Algorithm
---------
1. Load all medications for the patient with their caregiver-verified cues.
2. Start with every medication as a candidate.
3. For each (key, value) in the caller-supplied input cues:
   - Keep only candidates that have this cue_key AND whose cue_value matches
     (case-insensitive).
   - Medications that do NOT have a given cue_key are excluded — unknown cues
     must NEVER cause the resolver to invent an identity.
4. Evaluate remaining candidates:
   - 0  → NO_MATCH
   - 1  → UNIQUE  (medication_id returned)
   - 2+ → AMBIGUOUS  (candidate_ids + best_discriminator returned)

bestDiscriminator
-----------------
When AMBIGUOUS, find the cue_key where the remaining candidates have the most
differing values — i.e. the question that would best narrow the field.
Deterministic: keys are sorted alphabetically before inspection so the result
is always the same for the same inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.services.dawa_store import get_medications_for_patient, get_all_medication_cues_for_patient


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class VMRResult:
    """
    Returned by resolve().

    status: "UNIQUE" | "AMBIGUOUS" | "NO_MATCH"
    medication_id: set iff status == "UNIQUE"
    candidate_medication_ids: set iff status == "AMBIGUOUS"
    best_discriminator: set iff status == "AMBIGUOUS" and one exists
    """
    status: Literal["UNIQUE", "AMBIGUOUS", "NO_MATCH"]
    medication_id: str | None = None
    candidate_medication_ids: list[str] = field(default_factory=list)
    best_discriminator: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"status": self.status}
        if self.medication_id:
            d["medicationId"] = self.medication_id
        if self.candidate_medication_ids:
            d["candidateMedicationIds"] = self.candidate_medication_ids
        if self.best_discriminator:
            d["bestDiscriminator"] = self.best_discriminator
        return d


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------

def resolve(patient_id: str, cues: dict[str, str]) -> VMRResult:
    """
    Resolve medication identity from observed visual cues.

    Parameters
    ----------
    patient_id: str
        The patient whose verified medication cue library is searched.
    cues: dict[str, str]
        Observed cue key/value pairs, e.g. {"package_color": "white"}.

    Returns
    -------
    VMRResult with status UNIQUE | AMBIGUOUS | NO_MATCH.
    """
    # Load all medications and their verified cues for this patient
    medications = get_medications_for_patient(patient_id)
    if not medications:
        return VMRResult(status="NO_MATCH")

    all_cues: dict[str, dict[str, str]] = get_all_medication_cues_for_patient(patient_id)

    # Start with all medications as candidates
    candidates: list[str] = [m["id"] for m in medications]

    # Narrow down by each supplied cue
    for key, value in cues.items():
        remaining: list[str] = []
        for med_id in candidates:
            med_cues = all_cues.get(med_id, {})
            # The medication must have this cue key AND the value must match
            if key in med_cues and med_cues[key].lower() == value.lower().strip():
                remaining.append(med_id)
        candidates = remaining

    # Evaluate result
    if len(candidates) == 0:
        return VMRResult(status="NO_MATCH")

    if len(candidates) == 1:
        return VMRResult(status="UNIQUE", medication_id=candidates[0])

    # AMBIGUOUS — find the best discriminating cue
    discriminator = _best_discriminator(candidates, all_cues)
    return VMRResult(
        status="AMBIGUOUS",
        candidate_medication_ids=candidates,
        best_discriminator=discriminator,
    )


# ---------------------------------------------------------------------------
# Discriminator helper
# ---------------------------------------------------------------------------

def _best_discriminator(
    candidate_ids: list[str],
    all_cues: dict[str, dict[str, str]],
) -> str | None:
    """
    Return the cue_key that best discriminates the remaining candidates.

    A key discriminates when:
    - ALL candidates have that key (no missing data)
    - The candidates have at LEAST two distinct values for it

    Keys are sorted alphabetically for deterministic output.
    We prefer the key with the most distinct values (tiebreak: alphabetical).
    """
    # Collect all cue keys across all candidates
    all_keys: set[str] = set()
    for mid in candidate_ids:
        all_keys.update(all_cues.get(mid, {}).keys())

    best_key: str | None = None
    best_distinct: int = 0

    for key in sorted(all_keys):
        values: list[str] = []
        for mid in candidate_ids:
            val = all_cues.get(mid, {}).get(key)
            if val is None:
                # Key is missing for at least one candidate — skip
                values = []
                break
            values.append(val.lower())

        if not values:
            continue

        distinct = len(set(values))
        if distinct > 1 and distinct > best_distinct:
            best_distinct = distinct
            best_key = key

    return best_key


# ---------------------------------------------------------------------------
# Resolution guide builder (used by call_context.py)
# ---------------------------------------------------------------------------

def build_resolution_guide(patient_id: str) -> list[dict]:
    """
    Derive a human-readable resolution guide from VMR analysis.

    For each discriminating cue_key among the patient's medications,
    lists what each cue_value resolves to.

    Returns a list of dicts:
    [
      {
        "discriminator": "stripe_color",
        "mappings": [
          {"value": "blue", "medicationId": "metformin-500", "nickname": "raat wali goli"},
          {"value": "red",  "medicationId": "amlodipine-5",  "nickname": "BP wali goli"},
        ]
      },
      ...
    ]
    """
    medications = get_medications_for_patient(patient_id)
    all_cues = get_all_medication_cues_for_patient(patient_id)

    # Find all cue keys and group medications by value for each key
    all_keys: set[str] = set()
    for mid, cue_map in all_cues.items():
        all_keys.update(cue_map.keys())

    med_by_id = {m["id"]: m for m in medications}
    guide: list[dict] = []

    for key in sorted(all_keys):
        # Group by value
        by_value: dict[str, list[str]] = {}
        for mid in all_cues:
            val = all_cues[mid].get(key)
            if val:
                by_value.setdefault(val.lower(), []).append(mid)

        # Only include keys where different values map to different medications
        values = list(by_value.values())
        is_discriminating = len(by_value) > 1 and all(len(v) == 1 for v in values)
        if not is_discriminating:
            continue

        mappings = [
            {
                "value": val,
                "medicationId": mids[0],
                "nickname": med_by_id.get(mids[0], {}).get("nickname") or "",
                "clinicalName": med_by_id.get(mids[0], {}).get("clinical_name") or "",
            }
            for val, mids in sorted(by_value.items())
        ]
        guide.append({"discriminator": key, "mappings": mappings})

    return guide
