# DAWA — Codex Engineering Handoff

## 1. Product

DAWA is an Urdu-first voice medication companion designed primarily for
elderly and low-literacy patients in Pakistan.

Core idea:

"Every prescription assumes you can read. DAWA doesn't."

The patient does not need a smartphone application.

The caregiver manages medications through an Expo mobile application.
DAWA then calls the patient's normal Pakistani phone using Uplift AI.

---

## 2. High-Level Architecture

Caregiver Expo App
        |
        | Better Auth session
        v
TypeScript API Server
        |
        | validates caregiver session
        | injects trusted caregiver identity
        v
FastAPI DAWA Backend
        |
        +--> SQLite medication/domain storage
        |
        +--> deterministic VMR
        |
        +--> APScheduler
        |
        +--> verified Voice V2 context
        |
        v
Uplift AI Singapore API
        |
        v
Pakistani outbound phone call

---

## 3. Major Components

### Caregiver Mobile App

Location:

artifacts/caregiver-app/

Stack:

- Expo
- React Native
- TypeScript
- Expo Router
- Better Auth Expo client
- SecureStore session persistence

Primary screens/tabs:

- Home
- Medications
- Calls
- Settings

Additional screens:

- Google sign-in
- onboarding/demo-patient claim
- medication add/edit
- developer tools

The patient has NO app.

---

### TypeScript API Server

Location:

artifacts/api-server/

Responsibilities:

- public application API gateway
- Better Auth
- Google OAuth
- session validation
- strips untrusted identity headers
- injects trusted caregiver identity toward FastAPI
- proxies authenticated /api/dawa/* requests to FastAPI

Better Auth runs here, NOT in FastAPI.

FastAPI does not validate Google OAuth directly.

---

### FastAPI Backend

Location:

backend/

Important modules include:

- app/api/dawa.py
- app/services/dawa_store.py
- app/services/vmr.py
- app/services/call_context.py
- app/services/scheduler.py
- app/services/uplift.py
- app/services/voice_catalog.py
- app/services/conflict.py
- app/lib/caregiver.py

FastAPI owns medication-domain truth.

---

## 4. Uplift AI

Production calling uses Uplift AI Singapore:

https://ap-southeast-1.api.upliftai.org/v1

Real outbound calling to a Pakistani phone number has been manually proven.

No Twilio is used.

Uplift session lifecycle encountered in production:

dispatched
-> dialing
-> ringing
-> answered
-> completed

or failed.

Real session payloads use:

state
connected
createdAt
ringingAt
connectedAt
answeredAt
endedAt
durationSec

Do not revert to an older parser expecting standalone booleans.

One important invariant:

completed call != medication taken

Never infer adherence merely from telephony completion.

---

## 5. Voice V2

The original assistant was too generic and hallucinated/repeated prompts.

Voice V2 was introduced with:

- closed-world verified facts
- direct response to current patient question
- very short Urdu turns
- no generic reminder loop
- no invented medicine information
- no invented packaging cues
- no independent dose modification
- no recommendation to take another dose when the patient is uncertain
  whether it was already taken

The base assistant is intentionally generic.

Patient/medication truth is supplied per call by the backend.

Do not weaken these safety rules.

Do not hardcode a medicine in the base assistant.

---

## 6. Verified Medication Resolution — VMR

VMR is deterministic Python.

The LLM understands language.
The deterministic layer decides whether medicine identity has been resolved.

States:

- UNIQUE
- AMBIGUOUS
- NO_MATCH

No embeddings.
No LLM identity decision.
No fabricated confidence percentage.

Demo example:

Metformin:
- white box
- blue stripe

Amlodipine:
- white box
- red stripe

white alone -> AMBIGUOUS
white + blue -> Metformin
white + red -> Amlodipine

Clinical truth and patient-facing cues must remain separated.

---

## 7. Medication Safety Invariants

Never let the voice assistant independently:

- prescribe
- diagnose
- change dosage
- stop medication
- infer missing doctor instructions
- guess ambiguous medicine identity
- recommend another dose when double-dose uncertainty exists

Doctor/caregiver-entered structured fields are authoritative.

Free-text doctor instructions are supporting verified context and must not
silently override structured dose/schedule fields.

A deterministic conflict detector may warn but does not medically resolve
conflicts.

---

## 8. Scheduler

APScheduler is used for the hackathon MVP.

Timezone:

Asia/Karachi

Medication records contain schedule information and automatic-call settings.

The scheduler honors:

- active medication
- auto_call_enabled
- schedule_time
- idempotency
- one active Uplift outbound call at a time

Changing a schedule affects future occurrences only.

Historical dose events must remain unchanged.

The in-process APScheduler implementation is a demo/MVP limitation.
For production, use durable job infrastructure.

---

## 9. P3 Caregiver Product

P3 added:

- editable patient profile
- medication create/edit
- doctor's verified instructions
- medication recognition cues
- automatic-call toggle
- schedule editing
- backend-authoritative next-call calculation
- manual Call Now
- call history
- Uplift voice selection
- real Uplift voice preview
- four-tab caregiver UI

Voice selection belongs to the PATIENT, not a medication.

Selected Uplift voice should apply consistently to all calls for that patient.

---

## 10. P4 Better Auth

Better Auth runs in the TypeScript API Server.

Provider:

Google OAuth

Mobile app uses:

- @better-auth/expo
- SecureStore
- Expo deep linking

API server uses:

- Better Auth
- Google social provider
- Better Auth Expo server plugin

The API gateway protects /api/dawa/*.

Public routes include Better Auth's own /api/auth/* and health routes.

Authentication fails CLOSED.

If auth is not configured:
/api/dawa/* must never silently pass through.

---

## 11. Caregiver Ownership

Patient records include:

owner_user_id

This stores Better Auth's stable user ID.

Client-supplied identity is NEVER trusted.

The TypeScript gateway:

1. validates Better Auth session
2. removes incoming identity/internal-secret headers
3. injects trusted X-DAWA-CAREGIVER-ID
4. injects trusted X-DAWA-INTERNAL-SECRET
5. proxies to FastAPI

FastAPI verifies the internal gateway secret and caregiver ID.

Medication/call/patient access must remain owner-scoped.

Prevent IDOR.

---

## 12. Demo Patient

Demo patient:

Razia Bibi

ID:

razia-bibi

A first-time authenticated caregiver can claim the unowned demo patient
through the demo claim endpoint.

Claiming must be atomic.

Once claimed, another caregiver cannot take ownership.

Demo reset must not remove owner_user_id.

---

## 13. Databases

Runtime SQLite databases exist locally.

They MUST NOT be committed.

Examples may include:

- auth.db
- calls.db
- dawa_calls.db

Better Auth has its own SQLite auth database.

DAWA domain storage is separate.

Runtime DB files are intentionally gitignored.

---

## 14. Environment Variables

Required names include approximately:

UPLIFTAI_API_KEY
UPLIFT_ASSISTANT_ID
TEST_PHONE_NUMBER

BETTER_AUTH_SECRET
BETTER_AUTH_URL
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET

DAWA_INTERNAL_API_SECRET

EXPO_PUBLIC_API_BASE_URL

See .env.example.

Never commit actual values.

---

## 15. Security Rules

Never expose:

- UPLIFTAI_API_KEY
- GOOGLE_CLIENT_SECRET
- BETTER_AUTH_SECRET
- DAWA_INTERNAL_API_SECRET
- TEST_PHONE_NUMBER
- Better Auth cookies/tokens
- full provider configuration

Never print secret values during diagnostics.

Do not add auth bypasses for tests.

Tests should supply mocked trusted gateway headers instead.

---

## 16. Current Testing

Run backend tests from:

backend/

using the repository's configured Python environment.

Typical command:

python -m pytest -q

There are also TypeScript/API-server tests using Vitest.

Inspect package.json scripts before running.

Automated tests must NEVER:

- place real Uplift calls
- create real assistants
- update real Uplift assistants
- perform real Google OAuth
- mutate real Replit secrets

---

## 17. Replit Architecture

Historically this project ran several Replit workflows:

- DAWA Backend
- API Server
- Expo caregiver app / mobile preview

The Replit API server had a temporary .replit.dev development origin used
for Better Auth and Google OAuth.

Do not assume that URL is valid when running locally.

Google OAuth callback configuration must match the actual runtime domain.

---

## 18. Current Hackathon Priorities

Do NOT introduce major architecture unless fixing a confirmed blocker.

Avoid adding:

- Redis
- Celery
- PostgreSQL migration
- RAG
- vector DB
- OCR
- computer vision
- LangChain
- additional auth providers
- RBAC
- organizations
- admin dashboards

Remaining effort should prioritize:

1. end-to-end reliability
2. real mobile OAuth validation
3. real scheduled Uplift call validation
4. caregiver UI polish
5. final public branding
6. backup demo recording
7. presentation and pitch

---

## 19. Manual Core Demo

Expected demo sequence:

Caregiver opens app
-> authenticated caregiver
-> Razia dashboard
-> inspect/edit medication
-> configure automatic reminder
-> deterministic recognition demonstration
-> schedule/call triggers
-> patient's normal phone rings
-> DAWA speaks Urdu
-> patient asks which medicine
-> DAWA uses verified cues
-> patient suggests unverified dose change
-> DAWA refuses to change clinical truth
-> patient says they may already have taken dose
-> DAWA does not recommend another dose
-> call finishes
-> caregiver sees actual call status
-> completed is not automatically marked taken

---

## 20. Guidance for Codex

Before changing code:

1. inspect repository
2. read package manifests
3. inspect current environment assumptions
4. run safe tests
5. report architecture understanding
6. identify Replit-specific pieces

Do not perform destructive refactors before the hackathon.

Preserve safety invariants above.
