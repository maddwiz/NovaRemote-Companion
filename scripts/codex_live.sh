#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${HOME}/.codexremote/config.env"
if [[ -f "${CONFIG_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
fi

TMUX_BIN="${CODEXREMOTE_TMUX_BIN:-tmux}"
if ! command -v "${TMUX_BIN}" >/dev/null 2>&1; then
  echo "tmux not found: ${TMUX_BIN}" >&2
  exit 1
fi

CODEX_BIN="${CODEXREMOTE_CODEX_BIN:-$(command -v codex || true)}"
if [[ -z "${CODEX_BIN}" ]]; then
  echo "codex binary not found" >&2
  exit 1
fi

read -r -a CODEX_ARGS <<< "${CODEXREMOTE_CODEX_ARGS:---dangerously-bypass-approvals-and-sandbox}"
if [[ "${CODEX_ARGS[0]:-}" == "exec" ]]; then
  CODEX_ARGS=("${CODEX_ARGS[@]:1}")
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if command -v openssl >/dev/null 2>&1; then
  SUFFIX="$(openssl rand -hex 3)"
else
  SUFFIX="$RANDOM"
fi
SESSION="${CODEX_SESSION_NAME:-codexchat-${STAMP}-${SUFFIX}}"

if [[ "${1:-}" == "--session" ]]; then
  if [[ -z "${2:-}" ]]; then
    echo "--session requires a name" >&2
    exit 1
  fi
  SESSION="$2"
  shift 2
fi

if ! "${TMUX_BIN}" has-session -t "${SESSION}" 2>/dev/null; then
  "${TMUX_BIN}" new-session -d -s "${SESSION}" -c "$(pwd)"
  CMD=("${CODEX_BIN}" "${CODEX_ARGS[@]}" "$@")
  CMD_STR="$(printf '%q ' "${CMD[@]}")"
  CMD_STR="${CMD_STR% }"
  "${TMUX_BIN}" send-keys -t "${SESSION}" -l -- "${CMD_STR}"
  "${TMUX_BIN}" send-keys -t "${SESSION}" C-m
fi

exec "${TMUX_BIN}" attach -t "${SESSION}"
