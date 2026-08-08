---
name: P0-A vs future-phase code separation
description: How the DAWA backend separates P0-A canonical paths from future-phase features, and the constraints each path must obey.
---

## Rule
The P0-A canonical paths must never touch call_store, webhook logic, adherence parsing, admin auth, or medication-specific models.

## P0-A canonical paths
- `app/api/test_call.py` — only `POST /api/test-call` and `GET /api/test-call/status`; no imports except `dispatch_call` and `get_call_status` from uplift service
- `app/services/uplift.dispatch_call()` — uses `settings.uplift_assistant_id` directly; one POST to `/calls`; returns `{callId, status}` only
- `app/services/uplift.get_call_status()` — queries Uplift `/sessions` directly; no SQLite merge
- `app/main.py` — no `init_db()`, no startup warnings; `/health` returns `{status, service}` only

## Future-phase code location
- `app/api/future_calls.py` — `GET /api/call-log`, `POST /api/webhook/call-complete`, admin token, adherence extraction, CallRequest model
- **NOT registered** in `app/main.py` during P0-A
- future_calls imports `get_call_log` from uplift (which lazy-imports call_store)

## Why
The P0-A spec requires zero auth, zero body, zero SQLite, and a `{callId, status}`-only response.  
Future-phase code was inadvertently merged into the P0-A router by task agents, causing conformance violations.

## How to apply
Before any new route or import touches `app/api/test_call.py` or `app/services/uplift.dispatch_call()`, check this separation.  
Future features go in `future_calls.py` until explicitly graduated to P0-A.

## bootstrap
`scripts/create_uplift_assistant.py` calls `create_assistant()` from uplift service.  
The returned `realtimeAssistantId` must be set as `UPLIFT_ASSISTANT_ID` in Replit Secrets before any real call can be placed.  
`UPLIFT_ASSISTANT_ID` is required at call time (checked in `dispatch_call()`); server starts fine without it.
