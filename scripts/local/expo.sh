#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ahmadhassan/Desktop/Playground/Dawa"
APP_DIR="$ROOT/artifacts/caregiver-app"
ENV_FILE="$APP_DIR/.env.local"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. It should contain only public Expo configuration." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

missing=()
for name in EXPO_PUBLIC_API_BASE_URL
do
  if [[ -z "${!name:-}" ]]; then
    missing+=("$name")
  fi
done

if (( ${#missing[@]} > 0 )); then
  printf 'Missing required public Expo variable:\n' >&2
  printf '  %s\n' "${missing[@]}" >&2
  echo "Edit $ENV_FILE locally. Do not put server secrets in Expo env." >&2
  exit 1
fi

cd "$APP_DIR"
exec pnpm exec expo start
