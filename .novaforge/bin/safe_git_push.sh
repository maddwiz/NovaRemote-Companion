#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
"$repo_root/.novaforge/bin/verify_repo_lock.sh"

if [[ "$(pwd)" != "$repo_root" ]]; then
  echo "ERROR: safe_git_push.sh must be run from repo root: $repo_root" >&2
  exit 1
fi

branch="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "HEAD" ]]; then
  echo "ERROR: detached HEAD, refusing to push" >&2
  exit 1
fi

python3 - <<'PY' "$repo_root" "$branch"
import json
import pathlib
import sys

repo_root = pathlib.Path(sys.argv[1])
branch = sys.argv[2]
lock = json.loads((repo_root / ".novaforge" / "REPO_LOCK.json").read_text(encoding="utf-8"))
prefixes = lock.get("allowed_branch_prefixes", [])
if not any(branch.startswith(prefix) for prefix in prefixes):
    print(f"ERROR: branch '{branch}' does not match allowed prefixes: {prefixes}", file=sys.stderr)
    raise SystemExit(1)
print("Branch prefix allowed")
PY

git -C "$repo_root" push -u origin "$branch"
