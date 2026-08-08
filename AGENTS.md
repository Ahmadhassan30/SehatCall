# DAWA Codex Instructions

Before modifying this repository, read CODEX_CONTEXT.md completely.

CODEX_CONTEXT.md contains the authoritative engineering handoff from the
previous Replit Agent implementation.

Important rules:

- Preserve the existing Expo + TypeScript API Server + FastAPI architecture.
- Preserve Voice V2 safety behavior.
- VMR must remain deterministic.
- Never infer medication adherence from call completion.
- Never expose secrets.
- Never print environment variable values.
- Never commit .env files or runtime SQLite databases.
- Never place a real Uplift phone call during automated tests.
- Never mutate the real Uplift assistant unless explicitly requested.
- Never perform real Google OAuth during automated tests.
- Run existing tests before and after significant changes.
- Avoid major architecture changes before the hackathon.

Read CODEX_CONTEXT.md for all additional details.

## Local Development Rules

This project is now developed locally in VS Code as well as from the historical
Replit setup. Future Codex sessions must preserve the Expo caregiver app,
TypeScript API Server, and FastAPI backend architecture.

Local runtime targets:

- FastAPI backend: `http://localhost:8000`
- TypeScript API Server / Better Auth gateway: `http://localhost:8080`
- DAWA domain SQLite DB: `data/calls.db`
- Better Auth SQLite DB: `data/auth.db`
- Expo receives only public `EXPO_PUBLIC_*` values

Safety requirements:

- Read `CODEX_CONTEXT.md` first.
- Preserve DAWA Voice V2 safety behavior.
- Preserve deterministic VMR behavior.
- Preserve Better Auth fail-closed behavior.
- Preserve caregiver ownership isolation and IDOR protections.
- Never infer `TAKEN` from completed telephony.
- Never inspect, print, or summarize `.env.local` values.
- Never place real Uplift calls unless explicitly requested.
- Never create, update, or delete a real Uplift assistant unless explicitly requested.
- Never perform real Google OAuth during automated tests.
- Run relevant tests before and after meaningful changes.
- Avoid major architecture changes before the hackathon.
