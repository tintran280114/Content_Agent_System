from __future__ import annotations

import unittest

import httpx

import _bootstrap  # noqa: F401
from content_agent.ai.config import Role
from content_agent.ai.connectivity import probe_role_connection


class ConnectivityTests(unittest.TestCase):
    def test_missing_credential_does_not_make_a_request(self) -> None:
        result = probe_role_connection(Role.RESEARCH, env={})

        self.assertEqual(result.status, "missing")
        self.assertFalse(result.ready)
        self.assertIsNone(result.http_status)

    def test_gemini_probe_validates_endpoint_and_model_without_generation(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.host, "generativelanguage.googleapis.com")
            return httpx.Response(
                200,
                json={"models": [{"name": "models/gemini-3.1-flash-lite"}]},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = probe_role_connection(
                Role.RESEARCH,
                env={"GEMINI_API_KEY": "test-only"},
                client=client,
            )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.http_status, 200)
        self.assertTrue(result.ready)

    def test_network_failure_is_actionable_and_safe(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("blocked outbound network", request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = probe_role_connection(
                Role.COPYWRITER,
                env={"GROQ_API_KEY": "do-not-leak-this"},
                client=client,
            )

        self.assertEqual(result.status, "network")
        self.assertIn("unreachable", result.message)
        self.assertNotIn("do-not-leak-this", result.model_dump_json())

    def test_rejected_credential_is_distinct_from_network_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = probe_role_connection(
                Role.CRITIC,
                env={"GROQ_API_KEY": "invalid"},
                client=client,
            )

        self.assertEqual(result.status, "authentication")
        self.assertEqual(result.http_status, 401)

    def test_connected_but_missing_model_is_reported(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "another-model"}]})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = probe_role_connection(
                Role.COPYWRITER,
                env={"GROQ_API_KEY": "valid"},
                client=client,
            )

        self.assertEqual(result.status, "model_unavailable")
        self.assertIn("not available", result.message)


if __name__ == "__main__":
    unittest.main()
