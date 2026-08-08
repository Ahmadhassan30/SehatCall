# DAWA

Urdu-first medication companion for low-literacy patients.

---

## P0-A — Uplift Phone Call Integration Spike

This phase proves the Uplift AI realtime calling stack works end-to-end: a FastAPI backend places a real outbound Urdu AI call to a Pakistani phone number via the Uplift Singapore API.

**Nothing beyond this is implemented in P0-A.**  
PostgreSQL, VMR, memory, scheduler, caregiver UI, and medication features are all out of scope until a real two-way Urdu call succeeds.

---

### Required Replit Secrets

Set these in Replit → Secrets before running anything:

| Key | Required for |
|-----|-------------|
| `UPLIFTAI_API_KEY` | Every Uplift API operation |
| `TEST_PHONE_NUMBER` | Placing the test call (Pakistani format, e.g. `+923001234567`) |

`UPLIFT_ASSISTANT_ID` is added **after** running the bootstrap script (Step B below).

---

### Manual Test Sequence

Follow these steps in exact order.

#### A. Configure secrets

Add `UPLIFTAI_API_KEY` and `TEST_PHONE_NUMBER` to Replit Secrets.

#### B. Create the assistant

Run the one-time bootstrap script:

```bash
cd backend
python scripts/create_uplift_assistant.py
```

This creates a DAWA P0 Urdu realtime assistant through the Uplift Singapore endpoint.  
**It does NOT place a call.**

#### C. Copy the assistant ID

The script will print:

```
  realtimeAssistantId: <some-id>
```

Copy that value.

#### D. Save as Replit Secret

Add a new secret:

| Key | Value |
|-----|-------|
| `UPLIFT_ASSISTANT_ID` | the ID printed above |

#### E. Restart the workflow

Restart the DAWA backend workflow in Replit so the new secret is loaded.

#### F. Start FastAPI

The workflow runs:

```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

#### G. Verify health

```
GET /health
```

Expected response:

```json
{"status": "ok", "service": "dawa-p0"}
```

#### H. Place the test call

```
POST /api/test-call
```

Expected response:

```json
{"callId": "<id>", "status": "dispatched"}
```

`dispatched` means Uplift accepted the request and began dialling.  
**It does NOT mean the call was answered or that a conversation occurred.**

> ⚠️ Test only using your own phone number or another consenting tester.

#### I. Answer the phone

Pick up the call. The assistant will greet you in Urdu.  
Speak Urdu back naturally. The goal is a short two-way Urdu conversation.

#### J. Inspect call status

```
GET /api/test-call/status
```

Returns recent session states including: `dispatched`, `dialing`, `ringing`, `answered`, `completed`, `failed`, `failureReason`.

Poll at a cadence of every 2–5 seconds if you need live updates.

---

### If calling fails

1. Inspect the exact Uplift response from `GET /api/test-call/status`
2. Verify the Singapore base URL is used (`ap-southeast-1.api.upliftai.org`)
3. Verify `UPLIFT_ASSISTANT_ID` matches the ID from the bootstrap script
4. Verify `TEST_PHONE_NUMBER` is in international format (e.g. `+923001234567`)
5. Check Uplift account credits
6. Verify no other outbound call is currently active (Uplift allows one concurrent outbound call per organisation)
7. Report the concrete error before building any other DAWA feature

---

### Running the tests

```bash
cd backend
pip install -r requirements.txt
pytest
```

All tests mock Uplift HTTP — **no real calls are placed, zero credits consumed.**

---

### Stack

- Python 3 + FastAPI + Uvicorn
- Pydantic + pydantic-settings
- httpx (async HTTP)
- pytest + pytest-asyncio

All application code lives under `backend/`.
