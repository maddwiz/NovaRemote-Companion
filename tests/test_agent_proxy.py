import os
import unittest

os.environ.setdefault("CODEXREMOTE_TOKEN", "test-token")

from app.server import _is_allowed_agent_proxy_path, _normalize_agent_proxy_path


class AgentProxyHelpersTest(unittest.TestCase):
    def test_normalizes_root_to_health(self) -> None:
        self.assertEqual(_normalize_agent_proxy_path(""), "/health")
        self.assertEqual(_normalize_agent_proxy_path("/"), "/health")
        self.assertEqual(_normalize_agent_proxy_path("plans"), "/plans")

    def test_allows_expected_get_routes(self) -> None:
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/health"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/jobs"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/jobs/job-1"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/plans/plan-1"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/memory/status"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/workflows/status"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/workflows/list"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/workflows/item"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/terminal/sessions/term-1/output"))

    def test_allows_expected_post_routes(self) -> None:
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/plans"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/plans/plan-1/approve_async"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/plans/plan-1/reject"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/memory/recall"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/workflows/start"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/workflows/advance"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/terminal/sessions/term-1/input"))

    def test_rejects_unsupported_routes(self) -> None:
        self.assertFalse(_is_allowed_agent_proxy_path("GET", "/ws"))
        self.assertFalse(_is_allowed_agent_proxy_path("GET", "/plans/plan-1/stream"))
        self.assertFalse(_is_allowed_agent_proxy_path("POST", "/jobs/job-1"))
        self.assertFalse(_is_allowed_agent_proxy_path("POST", "/terminal/sessions/term-1/output"))


if __name__ == "__main__":
    unittest.main()
