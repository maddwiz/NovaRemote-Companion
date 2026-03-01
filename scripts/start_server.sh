#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
CONFIG_FILE="${HOME}/.codexremote/config.env"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Missing config file: ${CONFIG_FILE}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${CONFIG_FILE}"

if [[ -z "${CODEXREMOTE_TOKEN:-}" ]]; then
  echo "CODEXREMOTE_TOKEN is not set in ${CONFIG_FILE}" >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Missing virtualenv at ${VENV_DIR}" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

cd "${ROOT_DIR}"
exec uvicorn app.server:app --host "${CODEXREMOTE_BIND_HOST:-127.0.0.1}" --port "${CODEXREMOTE_BIND_PORT:-8787}"
