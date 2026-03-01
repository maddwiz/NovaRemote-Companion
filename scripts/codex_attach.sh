#!/usr/bin/env bash
set -euo pipefail

TMUX_BIN="${CODEXREMOTE_TMUX_BIN:-tmux}"
if ! command -v "${TMUX_BIN}" >/dev/null 2>&1; then
  echo "tmux not found: ${TMUX_BIN}" >&2
  exit 1
fi

if [[ -n "${1:-}" ]]; then
  exec "${TMUX_BIN}" attach -t "$1"
fi

mapfile -t SESSIONS < <(
  "${TMUX_BIN}" list-sessions -F '#{session_name}\t#{pane_current_command}' 2>/dev/null \
    | awk -F '\t' 'tolower($1) ~ /^codex/ || tolower($2) ~ /codex/ {print $1}'
)

if [[ "${#SESSIONS[@]}" -eq 0 ]]; then
  echo "No codex tmux sessions found." >&2
  exit 1
fi

echo "Select a session:"
for i in "${!SESSIONS[@]}"; do
  printf "%2d) %s\n" "$((i + 1))" "${SESSIONS[$i]}"
done
printf "> "
read -r IDX

if ! [[ "${IDX}" =~ ^[0-9]+$ ]] || (( IDX < 1 || IDX > ${#SESSIONS[@]} )); then
  echo "Invalid selection" >&2
  exit 1
fi

TARGET="${SESSIONS[$((IDX - 1))]}"
exec "${TMUX_BIN}" attach -t "${TARGET}"
