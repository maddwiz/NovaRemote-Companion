#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
lock_path="$repo_root/.novaforge/REPO_LOCK.json"

if [[ ! -f "$lock_path" ]]; then
  echo "ERROR: missing repo lock at $lock_path" >&2
  exit 1
fi

python3 - <<'PY' "$repo_root" "$lock_path"
import json
import pathlib
import subprocess
import sys

repo_root = pathlib.Path(sys.argv[1]).resolve()
lock_path = pathlib.Path(sys.argv[2]).resolve()
lock = json.loads(lock_path.read_text(encoding="utf-8"))

expected_root = pathlib.Path(lock["repo_root"]).resolve()
if repo_root != expected_root:
    print(f"ERROR: repo root mismatch: actual={repo_root} expected={expected_root}", file=sys.stderr)
    raise SystemExit(1)

actual_origin = subprocess.check_output(
    ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
    text=True,
).strip()
if actual_origin != lock["origin_url"]:
    print(f"ERROR: origin mismatch: actual={actual_origin} expected={lock['origin_url']}", file=sys.stderr)
    raise SystemExit(1)

print("Repo lock verified")
PY
