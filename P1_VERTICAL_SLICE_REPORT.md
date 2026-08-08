# DAWA P1 — Vertical Slice Report

**Date:** 2026-08-08  
**Scope:** Single-patient vertical demo slice on top of recovered P0-A codebase  
**Status:** ✅ COMPLETE

---

## What Was Built

### Backend (FastAPI / SQLite)

| File | Purpose |
|------|---------|
| `backend/app/services/dawa_store.py` | 6-table SQLite schema + idempotent seed + repository functions |
| `backend/app/services/vmr.py` | Deterministic VMR resolver (UNIQUE / AMBIGUOUS / NO_MATCH) |
| `backend/app/services/call_context.py` | Verified call context builder → `variables` + `additionalInstructions` for Uplift |
| `backend/app/api/dawa.py` | 4 new P1 routes |
| `backend/app/main.py` | Updated: lifespan init/seed + dawa router registered |

### New API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/dawa/demo` | Returns Razia Bibi, her medications (with verified cues), and recent dose events |
| POST | `/api/dawa/vmr/resolve` | Deterministic medication identity from visual cues |
| POST | `/api/dawa/demo-call` | Build verified context → dispatch Uplift call → create dose_event |
| GET | `/api/dawa/call-status` | Recent dose events merged with live Uplift telephony status |

### Database Schema (SQLite, same file as P0-A)

```
patients          — id, name, preferred_address, language, literacy_mode
medications       — id, patient_id, clinical_name, dosage, dose_instruction,
                    food_instruction, schedule_time, routine_anchor, nickname
medication_cues   — medication_id, cue_key, cue_value  (UNIQUE constraint)
dose_events       — id, patient_id, medication_id, scheduled_time,
                    call_id, call_status, adherence_outcome, created_at, updated_at
escalations       — id, patient_id, dose_event_id, reason, detail, created_at, resolved_at
patient_memory    — patient_id, memory_key, memory_value
```

### Demo Seed Data

**Patient:** Razia Bibi (`razia-bibi`) — preferred address "Ammi", language Urdu, voice-first

**Medications:**
| ID | Nickname | Clinical | Dosage | Package | Stripe |
|----|----------|----------|--------|---------|--------|
| `metformin-500` | raat wali goli | Metformin | 500 mg | WHITE | BLUE |
| `amlodipine-5` | BP wali goli | Amlodipine | 5 mg | WHITE | RED |

Both packages are white — intentional ambiguity demo for VMR.

### VMR Resolver Behaviour

```
{package_color: white}              → AMBIGUOUS  (bestDiscriminator: stripe_color)
{package_color: white, stripe_color: blue} → UNIQUE → metformin-500
{package_color: white, stripe_color: red}  → UNIQUE → amlodipine-5
{unknown_property: anything}         → NO_MATCH
```

- Deterministic, no LLM, no embeddings, no confidence values
- Unknown cues always → NO_MATCH (never invents an identity)

### Call Context

- **`variables`:** ≤ 3000 chars (JSON) — patient/medication facts, verified cues, VMR-derived resolution guide
- **`additionalInstructions`:** ≤ 2000 chars — Urdu system prompt with dose instructions, recognition protocol, and non-negotiable safety rules
- Context is derived entirely from database; no hardcoded strings in the call path

### Safety Invariants (enforced in instructions, tested)

1. Never changes prescribed dose
2. Never recommends a double dose if patient is uncertain
3. Only uses caregiver-verified cue descriptions
4. `call_status = 'completed'` ≠ `adherence_outcome = 'taken'` — always separate

### Caregiver App Rebuild

| File | Change |
|------|--------|
| `artifacts/caregiver-app/context/DawaContext.tsx` | New P1 context: loads demo data, VMR state, call dispatch + polling |
| `artifacts/caregiver-app/app/index.tsx` | Full rebuild: Razia Bibi dashboard, schedule cards, VMR demo card, safety card |
| `artifacts/caregiver-app/app/_layout.tsx` | `CallProvider` → `DawaProvider` |

### API Proxy

| File | Change |
|------|--------|
| `artifacts/api-server/src/routes/proxy.ts` | Transparent native-http proxy → `http://localhost:8000` |
| `artifacts/api-server/src/routes/index.ts` | Added proxy catch-all after health router |

The caregiver app reaches the Python backend through `https://<REPLIT_DEV_DOMAIN>/api/*` via the registered api-server artifact.

---

## Test Results

```
96 passed  (2.26 s)
  ├── 15 P0-A conformance tests    — all pass, zero regressions
  ├── 17 P0-A uplift service tests — all pass
  ├── 12 SQLite (call_store) tests — all pass
  ├──  3 health tests              — all pass
  ├── 30 future-calls tests        — all pass (still unregistered)
  └── 19 P1 DAWA tests             — all 19 pass (see below)
```

### P1 Test Coverage (19 tests in `tests/test_p1_dawa.py`)

| # | Test | Assertion |
|---|------|-----------|
| 1 | `test_seed_is_idempotent` | Double-seed → exactly 1 razia-bibi |
| 2 | `test_demo_data_has_two_medications` | Exactly metformin-500 + amlodipine-5 |
| 3 | `test_both_medications_have_white_package` | Both cues package_color=white |
| 4 | `test_white_only_is_ambiguous` | AMBIGUOUS, both candidates |
| 5 | `test_ambiguous_best_discriminator_is_stripe_color` | bestDiscriminator=stripe_color |
| 6 | `test_white_blue_resolves_to_metformin` | UNIQUE → metformin-500 |
| 7 | `test_white_red_resolves_to_amlodipine` | UNIQUE → amlodipine-5 |
| 8 | `test_unknown_cue_is_no_match` | NO_MATCH on unknown cue key |
| 9 | `test_vmr_result_has_no_confidence_or_probability_field` | No confidence/probability/score keys |
| 10 | `test_call_context_includes_only_verified_cues` | Metformin ctx has blue, not red |
| 11 | `test_patient_nickname_is_separate_from_clinical_name` | nickname ≠ clinical_name |
| 12 | `test_variables_within_documented_size_limit` | JSON ≤ 3000 chars |
| 13 | `test_instructions_within_documented_size_limit` | ≤ 2000 chars |
| 14 | `test_demo_call_uses_uplift_assistant_id_not_request` | assistantId from settings, not body |
| 15 | `test_demo_call_uses_test_phone_number_not_request` | `to` from TEST_PHONE_NUMBER |
| 16 | `test_demo_call_has_idempotency_key_header` | Idempotency-Key header present |
| 17 | `test_p0a_health_route_still_returns_exact_shape` | {status, service} only |
| 18 | `test_p0a_test_call_route_still_works` | POST /api/test-call still works |
| 19 | `test_completed_call_does_not_auto_set_adherence_to_taken` | adherenceOutcome=None after completed |

---

## What Was Explicitly NOT Built (per spec)

- ❌ Redis / Celery / Docker / LangChain
- ❌ Webhook endpoint (not verified against Uplift docs)
- ❌ New patient-facing frontend / patient app
- ❌ Multi-patient CRUD
- ❌ Custom RPC tools to Uplift (context passed as `variables` + `additionalInstructions` only)
- ❌ Probabilistic / ML-based VMR

---

## Known Pre-conditions for Live Call

1. Set `UPLIFT_ASSISTANT_ID` in Replit Secrets (run `scripts/create_uplift_assistant.py` first)
2. Set `TEST_PHONE_NUMBER` in Replit Secrets (Pakistani mobile number with country code)
3. Both "DAWA Backend" and "API Server" workflows must be running

Until secrets are set, `POST /api/dawa/demo-call` returns 503 with a descriptive message. All other P1 endpoints work without secrets.

---

*End of report.*
