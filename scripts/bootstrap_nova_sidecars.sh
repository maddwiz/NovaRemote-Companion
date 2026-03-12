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

ATTEMPTS=18
SLEEP_SECONDS=5
for (( attempt=1; attempt<=ATTEMPTS; attempt++ )); do
  if python3 "${ROOT_DIR}/scripts/validate_nova_sidecars.py" --repo-root "${ROOT_DIR}" --env-file "${ENV_FILE}" --live-check; then
    echo "Nova sidecars bootstrapped and validated."
    exit 0
  fi

  if (( attempt == ATTEMPTS )); then
    echo "Nova sidecars failed live validation after ${ATTEMPTS} attempts." >&2
    exit 1
  fi

  echo "Waiting for Nova sidecars to become healthy (${attempt}/${ATTEMPTS})..."
  sleep "${SLEEP_SECONDS}"
done
