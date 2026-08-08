# DAWA

Urdu-first medication companion for low-literacy patients.

---

## P0-B — Medication Reminder Behavior

P0-B adds the core DAWA value proposition on top of the proven P0-A call stack:
the assistant greets the patient, asks whether they took a **specific named medication** today,
confirms their yes/no response, and logs the call.

**P0-B scope:**
- Medication-aware Urdu assistant (asks about a named medicine, understands "ہاں"/"نہیں")
- `POST /api/test-call` accepts an optional `medication_name` field
- In-memory call log — inspect via `GET /api/call-log`
- No medical advice given by the assistant

**Out of scope:** PostgreSQL, multiple patients, scheduling, caregiver dashboard.

---

## Required Replit Secrets

Set these in Replit → Secrets before running anything:

| Key | Required for |
|-----|-------------|
| `UPLIFTAI_API_KEY` | Every Uplift API operation |
| `TEST_PHONE_NUMBER` | Placing calls (Pakistani format, e.g. `+923001234567`) |
| `DAWA_ADMIN_TOKEN` | Authorising `POST /api/test-call` and `GET /api/call-log` |

`UPLIFT_ASSISTANT_ID` is added **after** running the bootstrap script (Step B below).

> Set `DAWA_ADMIN_TOKEN` to any strong random string (e.g. `openssl rand -hex 32`).
> Both the call-trigger and call-log endpoints return 403 without it.

---

## Manual Test Sequence (P0-B)

Follow these steps in exact order.

### A. Configure secrets

Add `UPLIFTAI_API_KEY` and `TEST_PHONE_NUMBER` to Replit Secrets.

### B. Create the assistant

Run the one-time bootstrap script:

```bash
cd backend
python scripts/create_uplift_assistant.py
```

Optional — specify a default medication name (Urdu or romanised):

```bash
python scripts/create_uplift_assistant.py --medication "میٹفارمن"
```

This creates a DAWA Urdu medication-reminder assistant through the Uplift Singapore endpoint.
**It does NOT place a call.**

### C. Copy the assistant ID

The script will print:

```
  realtimeAssistantId: <some-id>
```

Copy that value.

### D. Save as Replit Secret

Add a new secret:

| Key | Value |
|-----|-------|
| `UPLIFT_ASSISTANT_ID` | the ID printed above |

### E. Restart the workflow

Restart the DAWA backend workflow in Replit so the new secret is loaded.

### F. Start FastAPI

The workflow runs:

```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### G. Verify health

```
GET /health
```

Expected response:

```json
{"status": "ok", "service": "dawa-p0"}
```

### H. Place a medication-reminder call

```
POST /api/test-call
Content-Type: application/json

{"medication_name": "میٹفارمن"}
```

`medication_name` is optional. If omitted, the assistant asks about "آپ کی دوائی" (your medicine).

Expected response:

```json
{
  "callId": "<id>",
  "status": "dispatched",
  "medication": "میٹفارمن",
  "logId": "<uuid>"
}
```

`dispatched` means Uplift accepted the request and began dialling.
**It does NOT mean the call was answered or that a conversation occurred.**

> ⚠️ Test only using your own phone number or another consenting tester.

### I. Answer the phone

Pick up the call. The assistant will:
1. Greet you in Urdu
2. Ask: *"کیا آپ نے آج اپنی دوائی [medication_name] لی ہے؟"*  
   ("Did you take your medicine [medication_name] today?")
3. Listen for *"ہاں"* (yes) or *"نہیں"* (no)
4. Confirm warmly and end the call

The assistant will **not** give medical advice, discuss dosage, or reveal internal details.

### J. Inspect call status

```
GET /api/test-call/status
```

Returns recent session states: `dispatched`, `dialing`, `ringing`, `answered`, `completed`, `failed`, `failureReason`.

Poll at a cadence of every 2–5 seconds if you need live updates.

### K. Inspect the call log

```
GET /api/call-log
```

Returns the in-memory call log (most-recent first):

```json
[
  {
    "logId": "<uuid>",
    "callId": "<id>",
    "medication": "میٹفارمن",
    "dispatchedAt": "2025-01-01T10:00:00+00:00",
    "status": "dispatched"
  }
]
```

> ⚠️ The call log is cleared on server restart (in-memory only). Persistent storage is a separate task.

---

## If calling fails

1. Inspect the exact Uplift response from `GET /api/test-call/status`
2. Verify the Singapore base URL is used (`ap-southeast-1.api.upliftai.org`)
3. Verify `UPLIFT_ASSISTANT_ID` matches the ID from the bootstrap script
4. Verify `TEST_PHONE_NUMBER` is in international format (e.g. `+923001234567`)
5. Check Uplift account credits
6. Verify no other outbound call is currently active (Uplift allows one concurrent outbound call per organisation)
7. Report the concrete error before building any other DAWA feature

---

## Running the tests

```bash
cd backend
pip install -r requirements.txt
pytest
```

All tests mock Uplift HTTP — **no real calls are placed, zero credits consumed.**

---

## Stack

- Python 3 + FastAPI + Uvicorn
- Pydantic + pydantic-settings
- httpx (async HTTP)
- pytest + pytest-asyncio

All application code lives under `backend/`.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `POST` | `/api/test-call` | Dispatch Urdu medication-reminder call |
| `GET` | `/api/test-call/status` | Recent Uplift session states |
| `GET` | `/api/call-log` | In-memory call log (cleared on restart) |
