#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ahmadhassan/Desktop/Playground/Dawa"
ENV_FILE="$ROOT/.env.local"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Create it from .env.example and fill secrets outside Codex chat." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export PORT="${PORT:-8080}"
export NODE_ENV="${NODE_ENV:-development}"
export DAWA_BACKEND_URL="${DAWA_BACKEND_URL:-http://localhost:8000}"
export BETTER_AUTH_DB_DIR="${BETTER_AUTH_DB_DIR:-$ROOT/data}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

missing=()
for name in \
  PORT \
  NODE_ENV \
  BETTER_AUTH_SECRET \
  BETTER_AUTH_URL \
  GOOGLE_CLIENT_ID \
  GOOGLE_CLIENT_SECRET \
  DAWA_INTERNAL_API_SECRET \
  DAWA_BACKEND_URL \
  BETTER_AUTH_DB_DIR
do
  if [[ -z "${!name:-}" ]]; then
    missing+=("$name")
  fi
done

if (( ${#missing[@]} > 0 )); then
  printf 'Missing required environment variable names/values:\n' >&2
  printf '  %s\n' "${missing[@]}" >&2
  echo "Edit $ENV_FILE locally; do not paste secret values into chat." >&2
  exit 1
fi

cd "$ROOT"
exec pnpm --filter @workspace/api-server run dev
