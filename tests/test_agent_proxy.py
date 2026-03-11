import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CODEXREMOTE_TOKEN", "test-token")

from app import server
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
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/jobs/job-1/stream"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/plans/plan-1"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/plans/plan-1/stream"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/templates"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/templates/template-1"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/gallery"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/events"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/events/stream"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/memory/status"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/runtime/governance"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/workflows/status"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/workflows/list"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/workflows/item"))
        self.assertTrue(_is_allowed_agent_proxy_path("GET", "/terminal/sessions/term-1/output"))

    def test_allows_expected_post_routes(self) -> None:
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/plans"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/plans/plan-1/approve_async"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/plans/plan-1/reject"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/templates/import"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/templates/template-1/launch"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/memory/recall"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/runtime/governance"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/runtime/jobs/cancel_all"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/workflows/start"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/workflows/advance"))
        self.assertTrue(_is_allowed_agent_proxy_path("POST", "/terminal/sessions/term-1/input"))

    def test_rejects_unsupported_routes(self) -> None:
        self.assertFalse(_is_allowed_agent_proxy_path("GET", "/ws"))
        self.assertFalse(_is_allowed_agent_proxy_path("GET", "/templates/template-1/launch"))
        self.assertFalse(_is_allowed_agent_proxy_path("POST", "/jobs/job-1"))
        self.assertFalse(_is_allowed_agent_proxy_path("POST", "/terminal/sessions/term-1/output"))

    def test_rejects_unapproved_control_route_families(self) -> None:
        denied_routes = [
            ("GET", "/mobile/status"),
            ("POST", "/mobile/action"),
            ("POST", "/execute/vision"),
            ("GET", "/browser/status"),
            ("POST", "/browser/action"),
            ("GET", "/voice/status"),
            ("POST", "/voice/transcribe"),
            ("POST", "/voice/synthesize"),
            ("GET", "/canvas/status"),
            ("POST", "/canvas/render"),
            ("GET", "/adapt/toggle"),
            ("POST", "/adapt/toggle"),
            ("GET", "/adapt/persona"),
        ]
        for method, path in denied_routes:
            with self.subTest(method=method, path=path):
                self.assertFalse(_is_allowed_agent_proxy_path(method, path))


class AgentCapabilitiesRouteTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        server.AGENT_CAPABILITIES_CACHE["payload"] = None
        server.AGENT_CAPABILITIES_CACHE["expires_at_ts"] = 0.0
        self.ensure_enabled = patch.object(server, "_ensure_novaadapt_enabled", return_value=None)
        self.ensure_enabled.start()

    async def asyncTearDown(self) -> None:
        self.ensure_enabled.stop()

    async def test_capabilities_route_caches_optional_route_support(self) -> None:
        with patch.object(
            server,
            "_probe_optional_service",
            new=AsyncMock(
                side_effect=[
                    {"configured": True, "ok": True},
                    {"configured": True, "status_code": 503, "detail": "upstream unavailable"},
                    {"configured": True, "status_code": 404, "detail": "missing"},
                    {"configured": True, "ok": True},
                    {"configured": True, "status_code": 404, "detail": "missing"},
                ]
            ),
        ) as probe_mock:
            first = await server.novaadapt_capabilities(force=False)
            second = await server.novaadapt_capabilities(force=False)

        self.assertEqual(probe_mock.await_count, 5)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["protocol_version"], server.COMPANION_PROTOCOL_VERSION)
        self.assertEqual(first["agent_contract_version"], server.AGENT_CONTRACT_VERSION)
        self.assertEqual(
            first["capabilities"],
            {
                "memoryStatus": True,
                "governance": True,
                "workflows": False,
                "templates": True,
                "templateGallery": False,
            },
        )

    async def test_force_refresh_bypasses_cached_capabilities(self) -> None:
        with patch.object(
            server,
            "_probe_optional_service",
            new=AsyncMock(side_effect=[{"configured": True, "ok": True}] * 10),
        ) as probe_mock:
            first = await server.novaadapt_capabilities(force=False)
            second = await server.novaadapt_capabilities(force=True)

        self.assertFalse(first["cached"])
        self.assertFalse(second["cached"])
        self.assertEqual(probe_mock.await_count, 10)


if __name__ == "__main__":
    unittest.main()
