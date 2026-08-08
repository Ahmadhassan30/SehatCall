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

export DAWA_DB_PATH="${DAWA_DB_PATH:-$ROOT/data/calls.db}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

missing=()
for name in \
  UPLIFTAI_API_KEY \
  UPLIFT_ASSISTANT_ID \
  TEST_PHONE_NUMBER \
  DAWA_INTERNAL_API_SECRET \
  DAWA_DB_PATH \
  LOG_LEVEL
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

cd "$ROOT/backend"
exec uv run --project "$ROOT" uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
