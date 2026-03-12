import contextlib
from dataclasses import replace
import json
import os
import socket
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch
import urllib.error
import urllib.request

import uvicorn

os.environ.setdefault("CODEXREMOTE_TOKEN", "test-token")

from app import server
from app.server import _is_allowed_agent_proxy_path, _normalize_agent_proxy_path


@contextlib.contextmanager
def _serve_app():
    original_ensure_enabled = server._ensure_novaadapt_enabled
    server._ensure_novaadapt_enabled = lambda: None

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    runner = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=runner.run, daemon=True)
    thread.start()
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.2):
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("Timed out waiting for companion server test app to start.")
        yield f"http://127.0.0.1:{port}"
    finally:
        runner.should_exit = True
        thread.join(timeout=2)
        server._ensure_novaadapt_enabled = original_ensure_enabled


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
                    {"configured": True, "ok": True},
                    {"configured": True, "status_code": 404, "detail": "missing"},
                    {"configured": True, "ok": True},
                    {"configured": True, "status_code": 404, "detail": "missing"},
                    {"configured": True, "ok": True},
                    {"configured": True, "status_code": 404, "detail": "missing"},
                    {"configured": True, "ok": True},
                ]
            ),
        ) as probe_mock:
            first = await server.novaadapt_capabilities(force=False)
            second = await server.novaadapt_capabilities(force=False)

        self.assertEqual(probe_mock.await_count, 12)
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
                "controlArtifacts": True,
                "mobileStatus": False,
                "browserStatus": True,
                "voiceStatus": False,
                "canvasStatus": True,
                "homeAssistantStatus": False,
                "mqttStatus": True,
            },
        )

    async def test_force_refresh_bypasses_cached_capabilities(self) -> None:
        with patch.object(
            server,
            "_probe_optional_service",
            new=AsyncMock(side_effect=[{"configured": True, "ok": True}] * 24),
        ) as probe_mock:
            first = await server.novaadapt_capabilities(force=False)
            second = await server.novaadapt_capabilities(force=True)

        self.assertFalse(first["cached"])
        self.assertFalse(second["cached"])
        self.assertEqual(probe_mock.await_count, 24)


class OptionalServiceProbeResilienceTest(unittest.IsolatedAsyncioTestCase):
    def test_proxy_json_request_degrades_connection_reset(self) -> None:
        with patch.object(
            server,
            "urlopen",
            side_effect=ConnectionResetError(54, "Connection reset by peer"),
        ):
            with self.assertRaises(server.HTTPException) as raised:
                server._proxy_json_request(
                    "http://127.0.0.1:9999",
                    "/health",
                    token=None,
                    timeout=1.0,
                )

        exc = raised.exception
        self.assertEqual(exc.status_code, 503)
        self.assertEqual(exc.detail, "Upstream unavailable: [Errno 54] Connection reset by peer")

    async def test_probe_optional_service_degrades_connection_reset(self) -> None:
        with patch.object(
            server,
            "urlopen",
            side_effect=ConnectionResetError(54, "Connection reset by peer"),
        ):
            result = await server._probe_optional_service(
                "http://127.0.0.1:9999",
                token=None,
                path="/health",
                timeout=1.0,
            )

        self.assertEqual(
            result,
            {
                "configured": True,
                "ok": False,
                "detail": "Upstream unavailable: [Errno 54] Connection reset by peer",
                "status_code": 503,
            },
        )

    async def test_health_degrades_optional_service_transport_errors(self) -> None:
        settings = replace(
            server.SETTINGS,
            novaadapt_bridge_url="http://127.0.0.1:9999",
            novaspine_url="http://127.0.0.1:9998",
        )
        with (
            patch.object(
                server,
                "SETTINGS",
                settings,
            ),
            patch.object(
                server,
                "urlopen",
                side_effect=[
                    ConnectionResetError(54, "Connection reset by peer"),
                    ConnectionResetError(54, "Connection reset by peer"),
                ],
            ),
        ):
            payload = await server.health()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["novaadapt"]["configured"], True)
        self.assertEqual(payload["novaadapt"]["ok"], False)
        self.assertEqual(payload["novaadapt"]["status_code"], 503)
        self.assertEqual(payload["novaspine"]["configured"], True)
        self.assertEqual(payload["novaspine"]["ok"], False)
        self.assertEqual(payload["novaspine"]["status_code"], 503)


class AgentProxyHttpRouteTest(unittest.TestCase):
    def test_denied_routes_return_404_over_http(self) -> None:
        denied_routes = [
            ("GET", "/browser/status"),
            ("GET", "/mobile/status"),
            ("POST", "/voice/transcribe"),
            ("POST", "/execute/vision"),
        ]

        with _serve_app() as base_url:
            for method, path in denied_routes:
                with self.subTest(method=method, path=path):
                    body = b"{}" if method == "POST" else None
                    request = urllib.request.Request(
                        f"{base_url}/agents{path}",
                        data=body,
                        headers={
                            "Authorization": "Bearer test-token",
                            "Content-Type": "application/json",
                        },
                        method=method,
                    )
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        urllib.request.urlopen(request, timeout=1)
                    error = raised.exception
                    try:
                        self.assertEqual(error.code, 404)
                        payload = json.loads(error.read().decode("utf-8"))
                        self.assertEqual(payload["detail"], "Unsupported NovaAdapt route.")
                    finally:
                        error.close()


if __name__ == "__main__":
    unittest.main()
