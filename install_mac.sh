#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}"
RUNTIME_DIR="${HOME}/.codexremote/runtime"
ROOT_DIR="${RUNTIME_DIR}"
VENV_DIR="${ROOT_DIR}/.venv"
CONFIG_DIR="${HOME}/.codexremote"
CONFIG_FILE="${CONFIG_DIR}/config.env"
BIN_DIR="${CONFIG_DIR}/bin"
ZSHRC_FILE="${HOME}/.zshrc"
PLIST_TEMPLATE="${ROOT_DIR}/launchd/com.desmond.codexremote.plist"
PLIST_TARGET="${HOME}/Library/LaunchAgents/com.desmond.codexremote.plist"
SERVICE_LABEL="com.desmond.codexremote"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "${CONFIG_DIR}"
mkdir -p "${BIN_DIR}"
mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${RUNTIME_DIR}"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude ".git/" \
    --exclude ".venv/" \
    --exclude "__pycache__/" \
    --exclude ".DS_Store" \
    "${SOURCE_DIR}/" "${RUNTIME_DIR}/"
else
  rm -rf "${RUNTIME_DIR}"
  mkdir -p "${RUNTIME_DIR}"
  cp -R "${SOURCE_DIR}/." "${RUNTIME_DIR}/"
  rm -rf "${RUNTIME_DIR}/.venv" "${RUNTIME_DIR}/.git"
fi

if [[ ! -f "${PLIST_TEMPLATE}" ]]; then
  echo "Missing launchd template: ${PLIST_TEMPLATE}" >&2
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "${ROOT_DIR}/requirements.txt"

if [[ -f "${CONFIG_FILE}" ]] && grep -q '^export CODEXREMOTE_TOKEN=' "${CONFIG_FILE}"; then
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
  TOKEN="${CODEXREMOTE_TOKEN}"
else
  if command -v openssl >/dev/null 2>&1; then
    TOKEN="$(openssl rand -hex 48)"
  else
    TOKEN="$(python - <<'PY'
import secrets
print(secrets.token_hex(48))
PY
)"
  fi
fi

CODEX_BIN="$(command -v codex || true)"
if [[ -z "${CODEX_BIN}" ]]; then
  CODEX_BIN="codex"
fi

cat > "${CONFIG_FILE}" <<CFG
export CODEXREMOTE_TOKEN="${TOKEN}"
export CODEXREMOTE_BIND_HOST="127.0.0.1"
export CODEXREMOTE_BIND_PORT="8787"
export CODEXREMOTE_TMUX_BIN="tmux"
export CODEXREMOTE_CODEX_BIN="${CODEX_BIN}"
export CODEXREMOTE_CODEX_ARGS="exec --dangerously-bypass-approvals-and-sandbox"
export CODEXREMOTE_DEFAULT_CWD="${HOME}"
export CODEXREMOTE_AUDIT_LOG="${CONFIG_DIR}/audit.log"
export CODEXREMOTE_NOVAADAPT_ENABLED="false"
export CODEXREMOTE_NOVAADAPT_BRIDGE_URL="http://127.0.0.1:9797"
export CODEXREMOTE_NOVAADAPT_BRIDGE_TOKEN=""
export CODEXREMOTE_NOVAADAPT_TIMEOUT_SECONDS="15"
export CODEXREMOTE_NOVASPINE_URL=""
export CODEXREMOTE_NOVASPINE_TOKEN=""
CFG
chmod 600 "${CONFIG_FILE}"

ROOT_ESCAPED="$(printf '%s' "${ROOT_DIR}" | sed 's/[\/&]/\\&/g')"
HOME_ESCAPED="$(printf '%s' "${HOME}" | sed 's/[\/&]/\\&/g')"
sed -e "s/__ROOT_DIR__/${ROOT_ESCAPED}/g" -e "s/__HOME__/${HOME_ESCAPED}/g" "${PLIST_TEMPLATE}" > "${PLIST_TARGET}"
chmod 644 "${PLIST_TARGET}"

chmod +x "${ROOT_DIR}/scripts/start_server.sh"
install -m 755 "${ROOT_DIR}/scripts/codex_live.sh" "${BIN_DIR}/codex-live"
install -m 755 "${ROOT_DIR}/scripts/codex_attach.sh" "${BIN_DIR}/codex-attach"

if [[ ! -f "${ZSHRC_FILE}" ]]; then
  touch "${ZSHRC_FILE}"
fi

if ! grep -q '^# >>> codex-remote mirror >>>$' "${ZSHRC_FILE}"; then
  cat >> "${ZSHRC_FILE}" <<'EOF'
# >>> codex-remote mirror >>>
export PATH="$HOME/.codexremote/bin:$PATH"

if command -v codex-live >/dev/null 2>&1; then
  codex() {
    if [[ -n "${CODEX_NO_TMUX:-}" || -n "${TMUX:-}" ]]; then
      command codex "$@"
      return
    fi

    case "${1:-}" in
      exec|review|login|logout|mcp|mcp-server|app-server|app|completion|sandbox|debug|apply|resume|fork|cloud|features|help|-h|--help|-V|--version)
        command codex "$@"
        return
        ;;
    esac

    codex-live "$@"
  }
fi
# <<< codex-remote mirror <<<
EOF
fi

launchctl bootout "gui/${UID}" "${PLIST_TARGET}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${UID}" "${PLIST_TARGET}"
launchctl enable "gui/${UID}/${SERVICE_LABEL}"
launchctl kickstart -k "gui/${UID}/${SERVICE_LABEL}"

TAILSCALE_IP=""
if command -v tailscale >/dev/null 2>&1; then
  TAILSCALE_IP="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
fi

echo ""
echo "Install complete"
echo "Service label: ${SERVICE_LABEL}"
echo "Config file: ${CONFIG_FILE}"
echo "Audit log: ${CONFIG_DIR}/audit.log"
echo "Helpers: ${BIN_DIR}/codex-live, ${BIN_DIR}/codex-attach"
echo "Token: ${TOKEN}"
if [[ -n "${TAILSCALE_IP}" ]]; then
  echo "Dashboard: http://${TAILSCALE_IP}:8787/?token=${TOKEN}"
else
  echo "Dashboard (local): http://127.0.0.1:8787/?token=${TOKEN}"
fi
echo ""
echo "For API calls: Authorization: Bearer ${TOKEN}"
echo "Open a new terminal (or run: source ~/.zshrc) to enable mirrored codex sessions from Mac."
