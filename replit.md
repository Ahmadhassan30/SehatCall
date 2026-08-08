# SehatCall

Urdu-first medication companion for low-literacy patients. P0-A is an integration spike proving that a FastAPI backend on Replit can place a real two-way Urdu AI phone call to a Pakistani phone number via the Uplift AI Singapore API.

## Run & Operate

### SehatCall Backend (Python / FastAPI)
- `cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000` — start FastAPI server (or use the "SehatCall Backend" workflow)
- `cd backend && python scripts/create_uplift_assistant.py` — one-time: create the Uplift Urdu assistant; prints `realtimeAssistantId` to save as `UPLIFT_ASSISTANT_ID` secret
- `cd backend && python -m pytest tests/ -v` — run all tests (zero Uplift credits consumed)

### Node.js workspace (pre-existing, not used in P0-A)
- `pnpm --filter @workspace/api-server run dev` — run the Express API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages

## Required Secrets

| Key | When needed |
|-----|------------|
| `UPLIFTAI_API_KEY` | Server startup and every Uplift call |
| `TEST_PHONE_NUMBER` | When `POST /api/test-call` is invoked |
| `UPLIFT_ASSISTANT_ID` | After running the bootstrap script; needed for `/api/test-call*` |

## Stack

### P0-A (active)
- Python 3.13 + FastAPI + Uvicorn
- Pydantic + pydantic-settings
- httpx (async HTTP client)
- pytest + pytest-asyncio

### Pre-existing workspace (not used in P0-A)
- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5 · DB: PostgreSQL + Drizzle ORM

## Where things live

```
backend/
  app/
    config.py          — Settings (pydantic-settings); UPLIFT_BASE_URL defined here only
    main.py            — FastAPI app, /health endpoint
    api/test_call.py   — POST /api/test-call, GET /api/test-call/status
    services/uplift.py — all Uplift HTTP calls (Singapore endpoint)
  scripts/
    create_uplift_assistant.py — one-time CLI bootstrap
  tests/
    test_health.py
    test_uplift_service.py
  requirements.txt
  pytest.ini
README.md              — P0-A manual test sequence (steps A–J)
```

## Architecture decisions

- **Singapore endpoint only** (`ap-southeast-1.api.upliftai.org`) — Pakistani outbound calling works only through this region.
- **`UPLIFT_ASSISTANT_ID` optional at startup** — the assistant doesn't exist until the bootstrap script creates it; missing-secret errors fire at call time with actionable messages.
- **Real calls gated behind deliberate HTTP request** — no startup hook, test, script, or workflow may automatically place a real call.
- **All Uplift HTTP centralised in `services/uplift.py`** — routes never make raw Uplift calls.
- **Tests mock all HTTP** — zero credits consumed by the test suite.

## Product

P0-A proves: FastAPI boots → bootstrap script creates Urdu assistant → `POST /api/test-call` dispatches real outbound call → Pakistani phone rings → developer answers → two-way Urdu conversation works → `GET /api/test-call/status` shows session lifecycle.

## User preferences

- Keep implementation small and readable; prefer explicit code over framework magic.
- Never expose credentials in logs, responses, or source code.
- All P0-A application code lives under `backend/`; minimal root-level changes only.

## Gotchas

- Run `create_uplift_assistant.py` BEFORE starting the server for the first time, then add the printed ID as `UPLIFT_ASSISTANT_ID` in Replit Secrets, then restart the workflow.
- `dispatched` ≠ answered. Uplift has a one-concurrent-outbound-call-per-organisation limit.
- `pydantic-settings` is a separate package from `pydantic`; `BaseSettings` lives in `pydantic_settings`.
- Custom workflow (`SehatCall Backend`) uses hardcoded port 8000; it does not receive `$PORT` from the artifact system.
