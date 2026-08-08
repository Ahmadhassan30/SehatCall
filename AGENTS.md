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
