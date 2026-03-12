#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import re
import sys
import tempfile
import threading
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

REQUIRED_NOVAADAPT_OPENAPI_PATHS = (
    "/health",
    "/jobs",
    "/jobs/{id}/stream",
    "/plans",
    "/plans/{id}/stream",
    "/memory/status",
    "/runtime/governance",
    "/workflows/status",
    "/workflows/list",
    "/workflows/item",
    "/workflows/start",
    "/workflows/advance",
    "/workflows/resume",
    "/events",
    "/events/stream",
    "/agents/templates",
    "/agents/gallery",
    "/agents/templates/import",
    "/agents/templates/{template_id}/launch",
    "/browser/status",
    "/voice/status",
    "/canvas/status",
    "/mobile/status",
    "/iot/homeassistant/status",
    "/iot/mqtt/status",
    "/control/artifacts",
)

REQUIRED_COMPANION_CAPABILITY_KEYS = (
    "memoryStatus",
    "governance",
    "workflows",
    "templates",
    "templateGallery",
    "controlArtifacts",
    "mobileStatus",
    "browserStatus",
    "voiceStatus",
    "canvasStatus",
    "homeAssistantStatus",
    "mqttStatus",
)

COMPANION_CAPABILITY_ROUTE_PROBES = {
    "controlArtifacts": "/agents/control/artifacts",
    "mobileStatus": "/agents/mobile/status",
    "browserStatus": "/agents/browser/status",
    "voiceStatus": "/agents/voice/status",
    "canvasStatus": "/agents/canvas/status",
    "homeAssistantStatus": "/agents/iot/homeassistant/status",
    "mqttStatus": "/agents/iot/mqtt/status",
}

EXPECTED_COMPANION_PROTOCOL_VERSION = "2026-03-11.1"
EXPECTED_AGENT_CONTRACT_VERSION = "2026-03-11.1"


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    message: str


class _ContractRouter:
    def list_models(self):
        class _Model:
            def __init__(self):
                self.name = "contract-local"
                self.model = "contract-model"
                self.provider = "openai-compatible"
                self.base_url = "http://127.0.0.1:11434/v1"

        return [_Model()]

    def health_check(self, model_names=None, probe_prompt="Reply with: OK"):
        _ = (model_names, probe_prompt)
        return [{"name": "contract-local", "ok": True, "latency_ms": 1.0}]

    def chat(
        self,
        messages,
        model_name=None,
        strategy="single",
        candidate_models=None,
        fallback_models=None,
    ):
        _ = (messages, model_name, strategy, candidate_models, fallback_models)
        raise RuntimeError("contract validator should not need model execution")


class _ContractDirectShell:
    def execute_action(self, action, dry_run=True):
        _ = (action, dry_run)
        return type(
            "_ExecutionResult",
            (),
            {
                "status": "preview" if dry_run else "ok",
                "output": "contract-simulated",
                "action": dict(action),
                "data": {},
            },
        )()


class _ContractMemoryBackend:
    def status(self):
        return {"ok": True, "enabled": True, "backend": "contract-memory"}

    def recall(self, query: str, top_k: int = 10):
        _ = (query, top_k)
        return []

    def augment(self, query: str, top_k: int = 5, *, min_score: float = 0.005, format_name: str = "xml"):
        _ = (query, top_k, min_score, format_name)
        return ""

    def ingest(self, text: str, *, source_id: str = "", metadata: dict | None = None):
        _ = (text, source_id, metadata)
        return {"ok": True}

    def track_event(self, event_type: str):
        _ = event_type
        return {"ok": True}

    def track_events_batch(self, event_types: list[str]):
        _ = event_types
        return {"ok": True}

    def consolidate(self, *, session_id: str = "", max_chunks: int = 32):
        _ = (session_id, max_chunks)
        return {"ok": True}

    def dream(self):
        return {"ok": True}


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


def _read_text(url: str, headers: dict[str, str] | None = None) -> str:
    req = request.Request(url, headers=headers or {})
    with request.urlopen(req, timeout=5) as response:
        return response.read().decode("utf-8")


@contextlib.contextmanager
def _prepend_import_paths(paths: list[Path]):
    inserted: list[str] = []
    for path in reversed(paths):
        raw = str(path)
        if raw not in sys.path:
            sys.path.insert(0, raw)
            inserted.append(raw)
    try:
        yield
    finally:
        for raw in inserted:
            while raw in sys.path:
                sys.path.remove(raw)


def _load_novaadapt_contract_runtime(novaadapt_repo_path: Path):
    core_path = (novaadapt_repo_path / "core").resolve()
    shared_path = (novaadapt_repo_path / "shared").resolve()
    if not core_path.exists() or not shared_path.exists():
        raise FileNotFoundError("NovaAdapt repo must contain core/ and shared/ directories")
    with _prepend_import_paths([core_path, shared_path]):
        importlib.invalidate_caches()
        server_module = importlib.import_module("novaadapt_core.server")
        service_module = importlib.import_module("novaadapt_core.service")
    return server_module.create_server, service_module.NovaAdaptService


def validate_novaadapt_repo_contract(repo_root: Path, novaadapt_repo_path: Path | None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if novaadapt_repo_path is None:
        issues.append(ValidationIssue("ERROR", "NovaAdapt repo path is required for contract validation"))
        return issues

    resolved_repo = novaadapt_repo_path.expanduser()
    if not resolved_repo.is_absolute():
        resolved_repo = (repo_root / resolved_repo).resolve()
    else:
        resolved_repo = resolved_repo.resolve()

    if not resolved_repo.exists():
        return [ValidationIssue("ERROR", f"NovaAdapt repo does not exist: {resolved_repo}")]

    try:
        create_server, novaadapt_service_cls = _load_novaadapt_contract_runtime(resolved_repo)
    except Exception as exc:
        return [ValidationIssue("ERROR", f"failed to load NovaAdapt contract runtime: {exc}")]

    contract_token = "contract-token"
    env_backup = {
        "NOVAADAPT_ENABLE_WORKFLOWS": os.environ.get("NOVAADAPT_ENABLE_WORKFLOWS"),
        "NOVAADAPT_ENABLE_WORKFLOWS_API": os.environ.get("NOVAADAPT_ENABLE_WORKFLOWS_API"),
    }
    os.environ["NOVAADAPT_ENABLE_WORKFLOWS"] = "1"
    os.environ["NOVAADAPT_ENABLE_WORKFLOWS_API"] = "1"

    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.joinpath("agent_gallery.json").write_text(
                json.dumps(
                    [
                        {
                            "template_id": "contract-gallery",
                            "name": "Contract Gallery",
                            "objective": "Validate contract routes",
                            "tags": ["contract"],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            service = novaadapt_service_cls(
                default_config=root / "config.json",
                db_path=root / "actions.db",
                plans_db_path=root / "plans.db",
                audit_db_path=root / "events.db",
                router_loader=lambda _path: _ContractRouter(),
                directshell_factory=_ContractDirectShell,
                memory_backend=_ContractMemoryBackend(),
            )
            server = create_server(
                "127.0.0.1",
                0,
                service,
                api_token=contract_token,
                audit_db_path=str(root / "events.db"),
            )
            host, port = server.server_address
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            headers = {"Authorization": f"Bearer {contract_token}"}
            try:
                health_payload = _read_json(f"http://{host}:{port}/health", headers)
                if not health_payload.get("ok"):
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /health did not return ok=true"))

                openapi_payload = _read_json(f"http://{host}:{port}/openapi.json", headers)
                openapi_paths = openapi_payload.get("paths")
                if not isinstance(openapi_paths, dict):
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /openapi.json did not return a paths object"))
                else:
                    missing_paths = [path for path in REQUIRED_NOVAADAPT_OPENAPI_PATHS if path not in openapi_paths]
                    if missing_paths:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                f"NovaAdapt openapi is missing required paths: {', '.join(missing_paths)}",
                            )
                        )

                memory_status = _read_json(f"http://{host}:{port}/memory/status", headers)
                if "backend" not in memory_status:
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /memory/status did not return backend"))

                governance = _read_json(f"http://{host}:{port}/runtime/governance", headers)
                if "paused" not in governance or "jobs" not in governance:
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /runtime/governance did not return paused/jobs"))

                workflows_status = _read_json(f"http://{host}:{port}/workflows/status", headers)
                if "enabled" not in workflows_status:
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /workflows/status did not return enabled"))

                workflows_list = _read_json(f"http://{host}:{port}/workflows/list", headers)
                if "count" not in workflows_list:
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /workflows/list did not return count"))

                templates_payload = _read_json(f"http://{host}:{port}/agents/templates", headers)
                if "templates" not in templates_payload:
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /agents/templates did not return templates"))

                gallery_payload = _read_json(f"http://{host}:{port}/agents/gallery", headers)
                if "templates" not in gallery_payload:
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /agents/gallery did not return templates"))

                events_payload = _read_json(f"http://{host}:{port}/events", headers)
                if not isinstance(events_payload, list):
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /events did not return a list payload"))

                events_stream = _read_text(
                    f"http://{host}:{port}/events/stream?timeout=1&interval=0.05&since_id=0",
                    headers,
                )
                if "event:" not in events_stream:
                    issues.append(ValidationIssue("ERROR", "NovaAdapt /events/stream did not return SSE output"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
    except Exception as exc:
        issues.append(ValidationIssue("ERROR", f"failed to validate NovaAdapt repo contract: {exc}"))
    finally:
        for key, value in env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    return issues


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
    health_protocol_version = str(health_payload.get("protocol_version") or "").strip()
    if not health_protocol_version:
        issues.append(ValidationIssue("ERROR", "Codex Remote /health did not return protocol_version"))
    elif health_protocol_version != EXPECTED_COMPANION_PROTOCOL_VERSION:
        issues.append(
            ValidationIssue(
                "ERROR",
                "Codex Remote /health protocol_version "
                f"{health_protocol_version!r} does not match expected {EXPECTED_COMPANION_PROTOCOL_VERSION!r}",
            )
        )
    health_agent_contract_version = str(health_payload.get("agent_contract_version") or "").strip()
    if not health_agent_contract_version:
        issues.append(ValidationIssue("ERROR", "Codex Remote /health did not return agent_contract_version"))
    elif health_agent_contract_version != EXPECTED_AGENT_CONTRACT_VERSION:
        issues.append(
            ValidationIssue(
                "ERROR",
                "Codex Remote /health agent_contract_version "
                f"{health_agent_contract_version!r} does not match expected {EXPECTED_AGENT_CONTRACT_VERSION!r}",
            )
        )

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
        try:
            capabilities_payload = _read_json(f"{base_url}/agents/capabilities", auth_headers)
            if not capabilities_payload.get("ok"):
                issues.append(ValidationIssue("ERROR", "Codex Remote /agents/capabilities did not return ok=true"))
            if not str(capabilities_payload.get("protocol_version") or "").strip():
                issues.append(ValidationIssue("ERROR", "Codex Remote /agents/capabilities did not return protocol_version"))
            elif str(capabilities_payload.get("protocol_version")).strip() != EXPECTED_COMPANION_PROTOCOL_VERSION:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "Codex Remote /agents/capabilities protocol_version "
                        f"{str(capabilities_payload.get('protocol_version')).strip()!r} "
                        f"does not match expected {EXPECTED_COMPANION_PROTOCOL_VERSION!r}",
                    )
                )
            if not str(capabilities_payload.get("agent_contract_version") or "").strip():
                issues.append(ValidationIssue("ERROR", "Codex Remote /agents/capabilities did not return agent_contract_version"))
            elif str(capabilities_payload.get("agent_contract_version")).strip() != EXPECTED_AGENT_CONTRACT_VERSION:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "Codex Remote /agents/capabilities agent_contract_version "
                        f"{str(capabilities_payload.get('agent_contract_version')).strip()!r} "
                        f"does not match expected {EXPECTED_AGENT_CONTRACT_VERSION!r}",
                    )
                )
            capabilities = capabilities_payload.get("capabilities")
            if not isinstance(capabilities, dict):
                issues.append(ValidationIssue("ERROR", "Codex Remote /agents/capabilities did not return a capabilities object"))
            else:
                missing_keys = [key for key in REQUIRED_COMPANION_CAPABILITY_KEYS if key not in capabilities]
                if missing_keys:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            f"Codex Remote /agents/capabilities is missing keys: {', '.join(missing_keys)}",
                        )
                    )
                else:
                    for capability_key, route in COMPANION_CAPABILITY_ROUTE_PROBES.items():
                        if not capabilities.get(capability_key):
                            continue
                        try:
                            _read_json(f"{base_url}{route}", auth_headers)
                        except Exception as exc:
                            issues.append(
                                ValidationIssue(
                                    "ERROR",
                                    f"Codex Remote {route} failed despite {capability_key}=true: {exc}",
                                )
                            )
        except (OSError, error.URLError, error.HTTPError, json.JSONDecodeError) as exc:
            issues.append(ValidationIssue("ERROR", f"failed to query /agents/capabilities: {exc}"))

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
    parser.add_argument(
        "--novaadapt-contract-check",
        action="store_true",
        help="boot the checked-out NovaAdapt repo and validate the server contract codex_remote depends on",
    )
    parser.add_argument(
        "--novaadapt-repo-path",
        type=Path,
        default=None,
        help="NovaAdapt repository checkout used for contract validation (defaults to env value or ../NovaAdapt)",
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
    if args.novaadapt_contract_check:
        contract_repo = args.novaadapt_repo_path
        if contract_repo is None and env_file is not None and env_file.exists():
            env_values = parse_env_file(env_file)
            contract_repo = resolve_repo_path(repo_root, env_values.get("NOVAADAPT_REPO_PATH"))
        if contract_repo is None:
            contract_repo = repo_root.parent / "NovaAdapt"
        issues.extend(validate_novaadapt_repo_contract(repo_root, contract_repo))
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
