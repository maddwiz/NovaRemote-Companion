import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.validate_nova_sidecars as validate_module  # noqa: E402

from scripts.validate_nova_sidecars import (  # noqa: E402
    parse_export_env_file,
    parse_env_file,
    validate_compose_text,
    validate_env_values,
    validate_live_runtime,
    validate_novaadapt_repo_contract,
)


class ValidateNovaSidecarsTest(unittest.TestCase):
    def test_parse_env_file_ignores_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env.nova-sidecars"
            env_path.write_text(
                "# comment\nNOVAADAPT_CORE_TOKEN=test-core\nNOVASPINE_TOKEN='test-spine'\n",
                encoding="utf-8",
            )
            values = parse_env_file(env_path)
            self.assertEqual(values["NOVAADAPT_CORE_TOKEN"], "test-core")
            self.assertEqual(values["NOVASPINE_TOKEN"], "test-spine")

    def test_validate_compose_text_accepts_expected_sidecar_file(self) -> None:
        compose_text = (ROOT / "docker-compose.nova-sidecars.yml").read_text(encoding="utf-8")
        issues = validate_compose_text(compose_text)
        self.assertEqual([], issues)

    def test_validate_compose_text_rejects_missing_services(self) -> None:
        issues = validate_compose_text("services:\n  novaspine:\n    image: python:3.12-slim\n")
        self.assertTrue(any(issue.level == "ERROR" for issue in issues))

    def test_validate_env_values_flags_placeholders_and_missing_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            values = {
                "NOVAADAPT_REPO_PATH": "../NovaAdapt",
                "NOVASPINE_REPO_PATH": "../NovaSpine",
                "NOVAADAPT_CORE_TOKEN": "change-me-core-token",
                "NOVAADAPT_BRIDGE_TOKEN": "change-me-bridge-token",
                "NOVASPINE_TOKEN": "change-me-spine-token",
                "NOVAADAPT_MEMORY_BACKEND": "novaspine-http",
                "NOVAADAPT_SPINE_URL": "",
                "NOVAADAPT_ENABLE_WORKFLOWS": "1",
                "NOVAADAPT_ENABLE_WORKFLOWS_API": "1",
                "NOVAADAPT_OLLAMA_HOST": "http://host.docker.internal:11434",
            }
            issues = validate_env_values(repo_root, values)
            errors = [issue.message for issue in issues if issue.level == "ERROR"]
            self.assertTrue(any("placeholder secret value" in message for message in errors))
            self.assertTrue(any("existing path" in message for message in errors))
            self.assertTrue(any("NOVAADAPT_SPINE_URL is required" in message for message in errors))

    def test_validate_env_values_accepts_real_paths_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "NovaAdapt").mkdir()
            (repo_root / "NovaSpine").mkdir()
            values = {
                "NOVAADAPT_REPO_PATH": "NovaAdapt",
                "NOVASPINE_REPO_PATH": "NovaSpine",
                "NOVAADAPT_CORE_TOKEN": "core-token",
                "NOVAADAPT_BRIDGE_TOKEN": "bridge-token",
                "NOVASPINE_TOKEN": "spine-token",
                "NOVAADAPT_MEMORY_BACKEND": "novaspine-http",
                "NOVAADAPT_SPINE_URL": "http://novaspine:8420",
                "NOVAADAPT_ENABLE_WORKFLOWS": "1",
                "NOVAADAPT_ENABLE_WORKFLOWS_API": "1",
                "NOVAADAPT_OLLAMA_HOST": "http://host.docker.internal:11434",
            }
            issues = validate_env_values(repo_root, values)
            self.assertEqual([], [issue for issue in issues if issue.level == "ERROR"])

    def test_parse_export_env_file_reads_shell_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.env"
            config_path.write_text(
                'export CODEXREMOTE_TOKEN="abc"\nexport CODEXREMOTE_BIND_PORT="8787"\n',
                encoding="utf-8",
            )
            values = parse_export_env_file(config_path)
            self.assertEqual(values["CODEXREMOTE_TOKEN"], "abc")
            self.assertEqual(values["CODEXREMOTE_BIND_PORT"], "8787")

    def test_validate_live_runtime_requires_token(self) -> None:
        issues = validate_live_runtime({})
        self.assertTrue(any(issue.level == "ERROR" for issue in issues))

    def test_validate_live_runtime_checks_agent_capabilities_contract(self) -> None:
        config = {
            "CODEXREMOTE_TOKEN": "token",
            "CODEXREMOTE_BIND_HOST": "127.0.0.1",
            "CODEXREMOTE_BIND_PORT": "8787",
            "CODEXREMOTE_NOVAADAPT_ENABLED": "true",
        }

        def fake_read_json(url: str, headers: dict[str, str] | None = None) -> dict:
            if url.endswith("/health"):
                return {
                    "ok": True,
                    "features": {"agents": True},
                    "novaadapt": {"ok": True},
                    "protocol_version": "2026-03-11.1",
                    "agent_contract_version": "2026-03-11.1",
                }
            if url.endswith("/agents/health"):
                return {"ok": True}
            if url.endswith("/agents/capabilities"):
                return {
                    "ok": True,
                    "protocol_version": "2026-03-11.1",
                    "agent_contract_version": "2026-03-11.1",
                    "capabilities": {
                        "memoryStatus": False,
                        "governance": True,
                        "workflows": True,
                        "templates": False,
                        "templateGallery": False,
                        "controlArtifacts": True,
                        "mobileStatus": True,
                        "browserStatus": True,
                        "voiceStatus": True,
                        "canvasStatus": True,
                        "homeAssistantStatus": True,
                        "mqttStatus": True,
                    },
                }
            if url.endswith("/agents/control/artifacts"):
                return {"items": []}
            if url.endswith("/agents/mobile/status"):
                return {"ok": True}
            if url.endswith("/agents/browser/status"):
                return {"ok": True}
            if url.endswith("/agents/voice/status"):
                return {"ok": True}
            if url.endswith("/agents/canvas/status"):
                return {"ok": True}
            if url.endswith("/agents/iot/homeassistant/status"):
                return {"ok": True}
            if url.endswith("/agents/iot/mqtt/status"):
                return {"ok": True}
            raise AssertionError(f"unexpected url: {url}")

        with patch.object(validate_module, "_read_json", side_effect=fake_read_json):
            issues = validate_live_runtime(config)

        self.assertEqual([], [issue for issue in issues if issue.level == "ERROR"])

    def test_validate_live_runtime_flags_enabled_route_probe_failures(self) -> None:
        config = {
            "CODEXREMOTE_TOKEN": "token",
            "CODEXREMOTE_BIND_HOST": "127.0.0.1",
            "CODEXREMOTE_BIND_PORT": "8787",
            "CODEXREMOTE_NOVAADAPT_ENABLED": "true",
        }

        def fake_read_json(url: str, headers: dict[str, str] | None = None) -> dict:
            if url.endswith("/health"):
                return {
                    "ok": True,
                    "features": {"agents": True},
                    "novaadapt": {"ok": True},
                    "protocol_version": "2026-03-11.1",
                    "agent_contract_version": "2026-03-11.1",
                }
            if url.endswith("/agents/health"):
                return {"ok": True}
            if url.endswith("/agents/capabilities"):
                return {
                    "ok": True,
                    "protocol_version": "2026-03-11.1",
                    "agent_contract_version": "2026-03-11.1",
                    "capabilities": {
                        "memoryStatus": False,
                        "governance": True,
                        "workflows": True,
                        "templates": False,
                        "templateGallery": False,
                        "controlArtifacts": True,
                        "mobileStatus": False,
                        "browserStatus": False,
                        "voiceStatus": False,
                        "canvasStatus": False,
                        "homeAssistantStatus": False,
                        "mqttStatus": False,
                    },
                }
            if url.endswith("/agents/control/artifacts"):
                raise RuntimeError("route probe failed")
            raise AssertionError(f"unexpected url: {url}")

        with patch.object(validate_module, "_read_json", side_effect=fake_read_json):
            issues = validate_live_runtime(config)

        self.assertTrue(
            any(
                issue.level == "ERROR"
                and "/agents/control/artifacts failed despite controlArtifacts=true" in issue.message
                for issue in issues
            )
        )

    def test_validate_live_runtime_flags_missing_capability_keys(self) -> None:
        config = {
            "CODEXREMOTE_TOKEN": "token",
            "CODEXREMOTE_BIND_HOST": "127.0.0.1",
            "CODEXREMOTE_BIND_PORT": "8787",
            "CODEXREMOTE_NOVAADAPT_ENABLED": "true",
        }

        def fake_read_json(url: str, headers: dict[str, str] | None = None) -> dict:
            if url.endswith("/health"):
                return {
                    "ok": True,
                    "features": {"agents": True},
                    "novaadapt": {"ok": True},
                    "protocol_version": "2026-03-11.1",
                    "agent_contract_version": "2026-03-11.1",
                }
            if url.endswith("/agents/health"):
                return {"ok": True}
            if url.endswith("/agents/capabilities"):
                return {
                    "ok": True,
                    "protocol_version": "2026-03-11.1",
                    "agent_contract_version": "2026-03-11.1",
                    "capabilities": {
                        "memoryStatus": False,
                        "governance": True,
                    },
                }
            raise AssertionError(f"unexpected url: {url}")

        with patch.object(validate_module, "_read_json", side_effect=fake_read_json):
            issues = validate_live_runtime(config)

        self.assertTrue(
            any(
                issue.level == "ERROR"
                and "missing keys" in issue.message
                and "workflows" in issue.message
                and "controlArtifacts" in issue.message
                for issue in issues
            )
        )

    def test_validate_live_runtime_flags_protocol_version_mismatch(self) -> None:
        config = {
            "CODEXREMOTE_TOKEN": "token",
            "CODEXREMOTE_BIND_HOST": "127.0.0.1",
            "CODEXREMOTE_BIND_PORT": "8787",
            "CODEXREMOTE_NOVAADAPT_ENABLED": "true",
        }

        def fake_read_json(url: str, headers: dict[str, str] | None = None) -> dict:
            if url.endswith("/health"):
                return {
                    "ok": True,
                    "features": {"agents": True},
                    "novaadapt": {"ok": True},
                    "protocol_version": "2026-03-01.0",
                    "agent_contract_version": "2026-03-11.1",
                }
            if url.endswith("/agents/health"):
                return {"ok": True}
            if url.endswith("/agents/capabilities"):
                return {
                    "ok": True,
                    "protocol_version": "2026-03-11.1",
                    "agent_contract_version": "2026-03-01.0",
                    "capabilities": {
                        "memoryStatus": False,
                        "governance": False,
                        "workflows": False,
                        "templates": False,
                        "templateGallery": False,
                        "controlArtifacts": False,
                        "mobileStatus": False,
                        "browserStatus": False,
                        "voiceStatus": False,
                        "canvasStatus": False,
                        "homeAssistantStatus": False,
                        "mqttStatus": False,
                    },
                }
            raise AssertionError(f"unexpected url: {url}")

        with patch.object(validate_module, "_read_json", side_effect=fake_read_json):
            issues = validate_live_runtime(config)

        self.assertTrue(
            any(
                issue.level == "ERROR"
                and "/health protocol_version" in issue.message
                for issue in issues
            )
        )
        self.assertTrue(
            any(
                issue.level == "ERROR"
                and "/agents/capabilities agent_contract_version" in issue.message
                for issue in issues
            )
        )

    def test_validate_novaadapt_repo_contract_flags_missing_repo(self) -> None:
        issues = validate_novaadapt_repo_contract(ROOT, ROOT / "does-not-exist")
        self.assertTrue(any(issue.level == "ERROR" and "does not exist" in issue.message for issue in issues))

    @unittest.skipUnless((ROOT.parent / "NovaAdapt").exists(), "sibling NovaAdapt repo required")
    def test_validate_novaadapt_repo_contract_accepts_local_checkout(self) -> None:
        issues = validate_novaadapt_repo_contract(ROOT, ROOT.parent / "NovaAdapt")
        self.assertEqual([], [issue for issue in issues if issue.level == "ERROR"])

    def test_main_allows_missing_env_file_during_live_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "docker-compose.nova-sidecars.yml").write_text(
                (ROOT / "docker-compose.nova-sidecars.yml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            config_path = repo_root / "config.env"
            config_path.write_text(
                'export CODEXREMOTE_TOKEN="abc"\n',
                encoding="utf-8",
            )

            with patch.object(validate_module, "validate_live_runtime", return_value=[]):
                result = validate_module.main(
                    [
                        "--repo-root",
                        str(repo_root),
                        "--env-file",
                        ".env.nova-sidecars",
                        "--live-check",
                        "--config-file",
                        str(config_path),
                    ]
                )

            self.assertEqual(0, result)

    def test_main_runs_novaadapt_contract_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "docker-compose.nova-sidecars.yml").write_text(
                (ROOT / "docker-compose.nova-sidecars.yml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            with patch.object(validate_module, "validate_novaadapt_repo_contract", return_value=[]):
                result = validate_module.main(
                    [
                        "--repo-root",
                        str(repo_root),
                        "--compose-only",
                        "--novaadapt-contract-check",
                    ]
                )

            self.assertEqual(0, result)


if __name__ == "__main__":
    unittest.main()
