# DAWA

**Urdu-first voice medication support for patients who should not need to read an app to stay cared for.**

DAWA is a hackathon project for elderly and low-literacy patients in Pakistan. A caregiver manages the patient's medication plan in an Expo app; DAWA calls the patient's normal phone and speaks in short, safe Urdu turns.

The core belief is simple:

> Every prescription assumes you can read. DAWA doesn't.

---

## What It Does

- Lets a caregiver create and manage a patient profile.
- Stores medications, schedules, doctor-entered instructions, and recognition cues.
- Calls the patient using Uplift AI's Singapore region.
- Speaks Urdu in a voice-first flow designed for low-literacy patients.
- Uses deterministic medication resolution instead of guessing.
- Shows caregiver call history and medication status.
- Protects all caregiver data behind Better Auth and owner-scoped access.

DAWA is not a medical decision-maker. It does not prescribe, diagnose, change doses, infer adherence, or tell a patient to take an extra dose.

---

## Architecture

```text
Expo Caregiver App
        |
        | Better Auth session
        v
TypeScript API Server :8080
        |
        | validates session
        | injects trusted caregiver identity
        v
FastAPI Backend :8000
        |
        +--> SQLite DAWA domain DB: data/calls.db
        +--> deterministic VMR
        +--> APScheduler
        +--> Uplift AI

Better Auth DB: data/auth.db
```

For physical-phone local development:

```text
Expo Go on phone
        |
        | HTTPS
        v
Cloudflare quick tunnel
        |
        v
Local TypeScript API Server :8080
        |
        v
Local FastAPI Backend :8000
```

---

## Safety Invariants

These are product rules, not implementation details:

- Completed call does **not** mean medication was taken.
- Voice V2 uses closed-world verified facts.
- VMR is deterministic: no embeddings, no LLM identity decision, no invented confidence.
- The assistant must not invent medicine information, packaging cues, schedules, side effects, or dosage changes.
- If the patient is unsure whether they already took a dose, DAWA must not recommend another dose.
- FastAPI trusts caregiver identity only after the TypeScript gateway validates Better Auth and injects trusted headers.
- `/api/dawa/*` must fail closed if auth is missing or invalid.

---

## Repository Map

```text
backend/                 FastAPI DAWA backend
artifacts/api-server/    TypeScript API Server, Better Auth, Google OAuth, proxy
artifacts/caregiver-app/ Expo caregiver app
lib/                     shared TypeScript libraries
scripts/local/           local VS Code/dev launch scripts
data/                    local runtime SQLite DBs, ignored by Git
```

---

## Local Setup

Install dependencies from the repo root:

```bash
cd /home/ahmadhassan/Desktop/Playground/Dawa
uv sync --locked --python 3.13
pnpm install --frozen-lockfile
```

The Python source of truth is the root `pyproject.toml` plus `uv.lock`. Do not use `backend/requirements.txt` as the primary install path; it is not the complete current backend dependency set.

---

## Environment Files

Never commit real secrets.

Server secrets live in:

```text
.env.local
```

Expo public config lives in:

```text
artifacts/caregiver-app/.env.local
```

Expo should contain only:

```text
EXPO_PUBLIC_API_BASE_URL=...
```

Do not put Uplift keys, Google secrets, Better Auth secrets, internal API secrets, phone numbers, cookies, or tokens into the Expo env file.

---

## Run Locally

Open separate terminals.

1. FastAPI backend:

```bash
cd /home/ahmadhassan/Desktop/Playground/Dawa
scripts/local/backend.sh
```

2. TypeScript API Server:

```bash
cd /home/ahmadhassan/Desktop/Playground/Dawa
scripts/local/api-server.sh
```

3. Cloudflare tunnel for phone/OAuth testing:

```bash
cd /home/ahmadhassan/Desktop/Playground/Dawa
cloudflared tunnel --url http://localhost:8080
```

Copy the printed `https://...trycloudflare.com` URL into:

- `.env.local` as `BETTER_AUTH_URL`
- `artifacts/caregiver-app/.env.local` as `EXPO_PUBLIC_API_BASE_URL`
- Google OAuth Authorized redirect URI as:

```text
https://YOUR-TUNNEL.trycloudflare.com/api/auth/callback/google
```

Then restart the API server and Expo.

4. Expo caregiver app:

```bash
cd /home/ahmadhassan/Desktop/Playground/Dawa
scripts/local/expo.sh
```

Scan the QR code with Expo Go.

---

## Health Checks

FastAPI:

```bash
curl http://localhost:8000/health
```

Expected:

```json
{"status":"ok","service":"dawa-p0"}
```

API Server auth health:

```bash
curl http://localhost:8080/api/auth/ok
```

Expected:

```json
{"ok":true}
```

Unauthenticated caregiver data must fail:

```bash
curl -i http://localhost:8080/api/dawa/patient
```

Expected: `401 Unauthorized`.

If this returns `200` without a session, stop immediately and fix auth before doing anything else.

---

## Tests

Backend:

```bash
cd /home/ahmadhassan/Desktop/Playground/Dawa/backend
uv run --project .. python -m pytest -q
```

API Server:

```bash
cd /home/ahmadhassan/Desktop/Playground/Dawa
pnpm --filter @workspace/api-server run test
```

Typechecks:

```bash
cd /home/ahmadhassan/Desktop/Playground/Dawa
pnpm run typecheck:libs
pnpm --filter @workspace/api-server run typecheck
pnpm --filter @workspace/caregiver-app run typecheck
```

Automated tests must not place Uplift calls, mutate assistants, perform Google OAuth, or contact a real phone number.

---

## Current Validation Snapshot

Last local validation during migration:

- Backend tests: `262 passed`
- API Server tests: `8 passed`
- FastAPI health: `200 OK`
- API auth health: `200 OK`
- Unauthenticated `/api/dawa/patient`: `401 Unauthorized`
- `data/calls.db`: integrity check `ok`
- `data/auth.db`: integrity check `ok`

The broader root typecheck currently reaches `artifacts/mockup-sandbox`, which has an unrelated duplicate React type identity issue. DAWA backend, API server, caregiver app, and shared library checks passed.

---

## Runtime Databases

Active local DBs:

```text
data/calls.db   DAWA domain data
data/auth.db    Better Auth data
```

These files are runtime state and must never be committed.

Legacy/stale candidates such as `backend/data/calls.db`, `backend/dawa_calls.db`, and `artifacts/data/auth.db` are not the active local targets for the current setup.

---

## VS Code Tasks

Available tasks:

- `DAWA: Backend`
- `DAWA: API Server`
- `DAWA: Expo`
- `DAWA: Start Local Stack`

Cloudflare is intentionally not bundled into the compound task, because its temporary URL must stay visible and must be copied into env and Google OAuth configuration.

---

## Demo Guardrails

Do not place a real DAWA/Uplift call unless the operator explicitly authorizes it.

The explicit phrase for a real call is:

```text
AUTHORIZE REAL TEST CALL
```

Until then, keep testing to local health, auth, UI loading, and mocked unit suites.

---

## Why This Is Cool

Most medication apps assume the patient has a smartphone, can read, can navigate forms, and can interpret medical reminders correctly.

DAWA flips that model:

- The caregiver does the app work.
- The patient receives a normal phone call.
- The conversation is in Urdu.
- The assistant stays inside verified facts.
- The system treats safety as the product, not a footnote.

It is small, practical, and built for the person who usually gets left out of polished health tech demos.
