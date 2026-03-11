#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request


REQUIRED_ENV_KEYS = (
    "NOVAADAPT_REPO_PATH",
    "NOVASPINE_REPO_PATH",
    "NOVAADAPT_CORE_TOKEN",
    "NOVAADAPT_BRIDGE_TOKEN",
    "NOVASPINE_TOKEN",
)

PLACEHOLDER_SECRET_PREFIXES = (
    "change-me-",
    "replace-with-",
)

REQUIRED_SERVICE_PATTERNS = (
    re.compile(r"^\s{2}novaspine:\s*$", re.MULTILINE),
    re.compile(r"^\s{2}novaadapt-core:\s*$", re.MULTILINE),
    re.compile(r"^\s{2}novaadapt-bridge:\s*$", re.MULTILINE),
)

REQUIRED_COMPOSE_SNIPPETS = (
    "${NOVASPINE_REPO_PATH:-../NovaSpine}",
    "${NOVAADAPT_REPO_PATH:-../NovaAdapt}",
    "${NOVAADAPT_CORE_TOKEN}",
    "${NOVAADAPT_BRIDGE_TOKEN}",
    "NOVAADAPT_MEMORY_BACKEND",
    "NOVAADAPT_SPINE_URL",
)


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    message: str


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def parse_export_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith("export "):
            continue
        key_value = line[len("export ") :]
        if "=" not in key_value:
            continue
        key, value = key_value.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def resolve_repo_path(repo_root: Path, raw_value: str | None) -> Path | None:
    if not raw_value:
        return None
    return (repo_root / raw_value).expanduser().resolve()


def validate_compose_text(compose_text: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for pattern in REQUIRED_SERVICE_PATTERNS:
        if not pattern.search(compose_text):
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"compose file is missing required service definition matching {pattern.pattern!r}",
                )
            )
    for snippet in REQUIRED_COMPOSE_SNIPPETS:
        if snippet not in compose_text:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"compose file is missing required reference {snippet}",
                )
            )
    return issues


def validate_env_values(repo_root: Path, values: dict[str, str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in REQUIRED_ENV_KEYS:
        if not values.get(key):
            issues.append(ValidationIssue("ERROR", f"{key} is required in the env file"))

    for key in ("NOVAADAPT_CORE_TOKEN", "NOVAADAPT_BRIDGE_TOKEN", "NOVASPINE_TOKEN"):
        value = values.get(key, "")
        if any(value.startswith(prefix) for prefix in PLACEHOLDER_SECRET_PREFIXES):
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"{key} still uses a placeholder secret value",
                )
            )

    for key in ("NOVAADAPT_REPO_PATH", "NOVASPINE_REPO_PATH"):
        resolved = resolve_repo_path(repo_root, values.get(key))
        if resolved is None or not resolved.exists():
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"{key} does not resolve to an existing path ({values.get(key, '')})",
                )
            )

    memory_backend = values.get("NOVAADAPT_MEMORY_BACKEND", "").strip()
    if memory_backend == "novaspine-http" and not values.get("NOVAADAPT_SPINE_URL", "").strip():
        issues.append(
            ValidationIssue(
                "ERROR",
                "NOVAADAPT_SPINE_URL is required when NOVAADAPT_MEMORY_BACKEND=novaspine-http",
            )
        )

    if not values.get("NOVAADAPT_ENABLE_WORKFLOWS", "").strip():
        issues.append(
            ValidationIssue(
                "WARNING",
                "NOVAADAPT_ENABLE_WORKFLOWS is unset; workflow APIs may be disabled",
            )
        )
    if not values.get("NOVAADAPT_ENABLE_WORKFLOWS_API", "").strip():
        issues.append(
            ValidationIssue(
                "WARNING",
                "NOVAADAPT_ENABLE_WORKFLOWS_API is unset; workflow APIs may be disabled",
            )
        )

    if not values.get("NOVAADAPT_OLLAMA_HOST", "").strip():
        issues.append(
            ValidationIssue(
                "WARNING",
                "NOVAADAPT_OLLAMA_HOST is empty; local Ollama-backed workflows may not work",
            )
        )

    return issues


def validate_sidecars(repo_root: Path, env_file: Path | None) -> list[ValidationIssue]:
    compose_path = repo_root / "docker-compose.nova-sidecars.yml"
    issues = validate_compose_text(compose_path.read_text(encoding="utf-8"))
    if env_file is None:
        return issues
    if not env_file.exists():
        issues.append(
            ValidationIssue(
                "ERROR",
                f"env file does not exist: {env_file}",
            )
        )
        return issues
    issues.extend(validate_env_values(repo_root, parse_env_file(env_file)))
    return issues


def _read_json(url: str, headers: dict[str, str] | None = None) -> dict:
    req = request.Request(url, headers=headers or {})
    with request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _codexremote_base_url(config_values: dict[str, str]) -> str:
    bind_host = config_values.get("CODEXREMOTE_BIND_HOST", "127.0.0.1")
    if bind_host in {"0.0.0.0", "::"}:
        bind_host = "127.0.0.1"
    bind_port = config_values.get("CODEXREMOTE_BIND_PORT", "8787")
    return f"http://{bind_host}:{bind_port}"


def validate_live_runtime(config_values: dict[str, str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    token = config_values.get("CODEXREMOTE_TOKEN", "").strip()
    if not token:
        return [ValidationIssue("ERROR", "CODEXREMOTE_TOKEN is required for live validation")]

    base_url = _codexremote_base_url(config_values)
    auth_headers = {"Authorization": f"Bearer {token}"}
    try:
        health_payload = _read_json(f"{base_url}/health", auth_headers)
    except (OSError, error.URLError, error.HTTPError, json.JSONDecodeError) as exc:
        return [ValidationIssue("ERROR", f"failed to query Codex Remote health: {exc}")]

    if not health_payload.get("ok"):
        issues.append(ValidationIssue("ERROR", "Codex Remote health endpoint did not return ok=true"))
    if not health_payload.get("features", {}).get("agents"):
        issues.append(ValidationIssue("ERROR", "Codex Remote agents feature is not enabled"))

    novaadapt_block = health_payload.get("novaadapt") or {}
    if config_values.get("CODEXREMOTE_NOVAADAPT_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }:
        if not novaadapt_block.get("ok"):
            issues.append(ValidationIssue("ERROR", "NovaAdapt bridge is not healthy from Codex Remote /health"))
        try:
            agents_health = _read_json(f"{base_url}/agents/health", auth_headers)
            if not agents_health.get("ok"):
                issues.append(ValidationIssue("ERROR", "Codex Remote /agents/health did not return ok=true"))
        except (OSError, error.URLError, error.HTTPError, json.JSONDecodeError) as exc:
            issues.append(ValidationIssue("ERROR", f"failed to query /agents/health: {exc}"))

    novaspine_url = config_values.get("CODEXREMOTE_NOVASPINE_URL", "").strip()
    novaspine_token = config_values.get("CODEXREMOTE_NOVASPINE_TOKEN", "").strip()
    if novaspine_url:
        if not health_payload.get("novaspine", {}).get("ok"):
            issues.append(ValidationIssue("ERROR", "NovaSpine is not healthy from Codex Remote /health"))
        if not novaspine_token:
            issues.append(ValidationIssue("ERROR", "CODEXREMOTE_NOVASPINE_TOKEN is required for live NovaSpine validation"))
        else:
            try:
                spine_payload = _read_json(
                    f"{novaspine_url.rstrip('/')}/api/v1/health",
                    {"Authorization": f"Bearer {novaspine_token}"},
                )
                if spine_payload.get("status") != "ok":
                    issues.append(ValidationIssue("ERROR", "NovaSpine /api/v1/health did not return status=ok"))
            except (OSError, error.URLError, error.HTTPError, json.JSONDecodeError) as exc:
                issues.append(ValidationIssue("ERROR", f"failed to query NovaSpine health: {exc}"))

    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the codex_remote + NovaAdapt + NovaSpine sidecar package.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="codex_remote repository root",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env.nova-sidecars"),
        help="sidecar env file to validate",
    )
    parser.add_argument(
        "--compose-only",
        action="store_true",
        help="validate only the compose package and skip env-file checks",
    )
    parser.add_argument(
        "--live-check",
        action="store_true",
        help="also validate the currently running Codex Remote + sidecar runtime",
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=Path.home() / ".codexremote" / "config.env",
        help="Codex Remote config file used for live runtime validation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    env_file = None if args.compose_only else args.env_file.expanduser()
    if env_file is not None and not env_file.is_absolute():
        env_file = (repo_root / env_file).resolve()
    issues: list[ValidationIssue] = []
    if env_file is not None and not env_file.exists() and args.live_check:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"env file does not exist: {env_file}; skipping package env checks and continuing with live validation",
            )
        )
        env_file = None

    issues.extend(validate_sidecars(repo_root, env_file))
    if args.live_check:
        config_file = args.config_file.expanduser().resolve()
        if not config_file.exists():
            issues.append(ValidationIssue("ERROR", f"config file does not exist: {config_file}"))
        else:
            issues.extend(validate_live_runtime(parse_export_env_file(config_file)))
    if issues:
        for issue in issues:
            stream = sys.stderr if issue.level == "ERROR" else sys.stdout
            print(f"[{issue.level}] {issue.message}", file=stream)
        if any(issue.level == "ERROR" for issue in issues):
            return 1
    print("Sidecar validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
