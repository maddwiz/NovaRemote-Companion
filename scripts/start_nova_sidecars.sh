#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${ROOT_DIR}/.env.nova-sidecars}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  echo "Copy ${ROOT_DIR}/.env.nova-sidecars.example to ${ENV_FILE} and customize it first." >&2
  exit 1
fi

python3 "${ROOT_DIR}/scripts/validate_nova_sidecars.py" --repo-root "${ROOT_DIR}" --env-file "${ENV_FILE}"

docker compose \
  --env-file "${ENV_FILE}" \
  -f "${ROOT_DIR}/docker-compose.nova-sidecars.yml" \
  up -d --build

echo "Nova sidecars started."
echo "Run this to validate the live stack:"
echo "  python3 ${ROOT_DIR}/scripts/validate_nova_sidecars.py --repo-root ${ROOT_DIR} --env-file ${ENV_FILE} --live-check"
