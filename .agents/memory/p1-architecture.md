---
name: P1 Architecture
description: Key decisions and constraints for the DAWA P1 vertical slice build.
---

## Core Structure

- New tables in the SAME SQLite file as P0-A (`DAWA_DB_PATH`). `isolate_db` autouse fixture covers both.
- `dawa_store.py` — all P1 DB access (init, seed, repository functions).
- `vmr.py` — deterministic resolver: filter-by-cue algorithm, no LLM.
- `call_context.py` — builds `variables` (≤3000 chars JSON) + `additionalInstructions` (≤2000 chars) for Uplift.
- `app/api/dawa.py` — 4 routes prefixed `/api/dawa/*`.
- `app/main.py` — lifespan runs `init_dawa_db()` + `seed_demo_data()` on startup.

## Module Reload Order for Tests

Tests that exercise the P1 API must reload in this order to get fresh Settings:
1. `app.config`
2. `app.services.uplift`
3. `app.api.test_call`
4. `app.api.dawa`
5. `app.main`

Then call `init_dawa_db()` + `seed_demo_data()` explicitly (don't rely on lifespan in non-CM TestClient).

## API Proxy Chain

Caregiver app → `https://${EXPO_PUBLIC_DOMAIN}/api/*`
→ api-server artifact (port 8080, previewPath `/api`, paths `["/api"]`)
→ `proxy.ts` (native http, no extra deps) → `http://localhost:8000/api/*`
→ Python DAWA backend.

**Why:** Python backend is not a Replit artifact (no previewPath), so unreachable via Replit proxy directly.

## VMR Algorithm

1. Load all medications + their verified cues for patient.
2. Start candidates = all medications.
3. For each input cue (key, value): keep only candidates that HAVE this key AND value matches (case-insensitive). Meds without the key are excluded.
4. 0 → NO_MATCH; 1 → UNIQUE; 2+ → AMBIGUOUS + bestDiscriminator.
5. bestDiscriminator = first cue_key (alphabetical) where ALL candidates have the key but values differ.

**Why:** No ML, no fuzzy matching — unknown cues must never invent an identity.

## Caregiver App URL

Default API base URL in DawaContext: `https://${EXPO_PUBLIC_DOMAIN}` (auto-resolved on Replit).
User can override via Settings modal → stored in AsyncStorage key `dawa_api_url`.

## Completed Call ≠ TAKEN

`dose_events.call_status = 'completed'` is telephony only.
`dose_events.adherence_outcome` remains NULL until explicitly set.
This invariant is tested in `test_p1_dawa.py::test_completed_call_does_not_auto_set_adherence_to_taken`.

## Pre-conditions for Live Call

Set both `UPLIFT_ASSISTANT_ID` and `TEST_PHONE_NUMBER` in Replit Secrets.
Without them, `POST /api/dawa/demo-call` returns 503 (descriptive message).
All other P1 endpoints work without secrets.
