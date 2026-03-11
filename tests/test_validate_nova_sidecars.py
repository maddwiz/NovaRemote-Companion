import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_nova_sidecars import (  # noqa: E402
    ValidationIssue,
    parse_env_file,
    validate_compose_text,
    validate_env_values,
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


if __name__ == "__main__":
    unittest.main()
