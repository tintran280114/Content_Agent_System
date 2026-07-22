from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from content_agent.ai.errors import ErrorCode, ProviderError, normalize_provider_exception


class FakeHttpError(Exception):
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        super().__init__("unsafe upstream details intentionally ignored")
        self.status_code = status_code
        self.body = body or {}


class ConnectError(Exception):
    pass


class ErrorTests(unittest.TestCase):
    def test_rate_limit_is_retryable_and_safe(self) -> None:
        error = normalize_provider_exception(
            FakeHttpError(429, {"message": "quota exceeded"}),
            provider="groq",
            model="model",
        )
        self.assertEqual(error.code, ErrorCode.RATE_LIMIT)
        self.assertTrue(error.retryable)
        self.assertNotIn("unsafe", str(error))

    def test_permission_is_not_retryable(self) -> None:
        error = normalize_provider_exception(
            FakeHttpError(403), provider="github_models", model="openai/test"
        )
        self.assertEqual(error.code, ErrorCode.PERMISSION_DENIED)
        self.assertFalse(error.retryable)

    def test_connection_class_is_normalized_without_unsafe_details(self) -> None:
        error = normalize_provider_exception(
            ConnectError("upstream detail must stay private"),
            provider="gemini",
            model="model",
        )
        self.assertEqual(error.code, ErrorCode.NETWORK)
        self.assertTrue(error.retryable)
        self.assertEqual(str(error), "Could not connect to provider.")
        self.assertNotIn("upstream", str(error))

    def test_error_dict_has_handoff_fields(self) -> None:
        error = ProviderError(
            ErrorCode.TIMEOUT,
            "Provider request timed out.",
            provider="gemini",
            model="model",
            retryable=True,
            status_code=504,
        )
        self.assertEqual(
            set(error.as_dict()),
            {"code", "message", "provider", "model", "retryable", "status_code"},
        )


if __name__ == "__main__":
    unittest.main()
