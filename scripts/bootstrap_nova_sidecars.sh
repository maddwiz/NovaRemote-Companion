#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${ROOT_DIR}/.env.nova-sidecars}"
EXAMPLE_ENV="${ROOT_DIR}/.env.nova-sidecars.example"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${EXAMPLE_ENV}" "${ENV_FILE}"
  echo "Created ${ENV_FILE} from the example template."
  echo "Edit repo paths and tokens, then rerun this command."
  exit 0
fi

python3 "${ROOT_DIR}/scripts/validate_nova_sidecars.py" --repo-root "${ROOT_DIR}" --env-file "${ENV_FILE}"

docker compose \
  --env-file "${ENV_FILE}" \
  -f "${ROOT_DIR}/docker-compose.nova-sidecars.yml" \
  up -d --build

python3 "${ROOT_DIR}/scripts/validate_nova_sidecars.py" --repo-root "${ROOT_DIR}" --env-file "${ENV_FILE}" --live-check

echo "Nova sidecars bootstrapped and validated."
