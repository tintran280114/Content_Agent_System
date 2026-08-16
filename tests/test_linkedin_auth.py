from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet

import _bootstrap  # noqa: F401
from content_agent.linkedin_auth import (
    LinkedInOAuthClient,
    LinkedInTokenManager,
    build_linkedin_authorization_url,
)
from content_agent.meta_auth import EncryptedTokenStore


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return FakeResponse(200, {"access_token": "private-token", "expires_in": 5_184_000})

    def get(self, url: str, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return FakeResponse(200, {"sub": "member-123"})


class LinkedInAuthTests(unittest.TestCase):
    def test_authorization_url_has_minimal_scopes_state_and_no_secret(self) -> None:
        url = build_linkedin_authorization_url(
            client_id="client-id",
            redirect_uri="https://example.test/callback",
            state="csrf-state",
        )
        self.assertIn("openid", url)
        self.assertIn("profile", url)
        self.assertIn("w_member_social", url)
        self.assertIn("csrf-state", url)
        self.assertNotIn("secret", url)

    def test_code_exchange_returns_person_urn_without_leaking_secret_in_url(self) -> None:
        client = FakeClient()
        token, urn, expires_in = LinkedInOAuthClient(client=client).exchange_code(
            code="authorization-code",
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/callback",
        )
        self.assertEqual((token, urn, expires_in), ("private-token", "urn:li:person:member-123", 5_184_000))
        self.assertNotIn("client-secret", client.calls[0]["url"])
        self.assertEqual(client.calls[0]["data"]["client_secret"], "client-secret")
        self.assertEqual(client.calls[1]["headers"]["Authorization"], "Bearer private-token")

    def test_token_is_encrypted_and_resolves_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EncryptedTokenStore(Path(directory) / "tokens.enc", Fernet.generate_key())
            now = datetime(2026, 8, 11, tzinfo=UTC)
            LinkedInTokenManager(env={}, store=store, now=lambda: now).save(
                "LINKEDIN_TEST_TOKEN",
                access_token="private-token",
                person_urn="urn:li:person:member-123",
                expires_in=5_184_000,
            )
            self.assertNotIn(b"private-token", store.path.read_bytes())
            loaded = LinkedInTokenManager(env={}, store=store, now=lambda: now)
            self.assertEqual(loaded.resolve("LINKEDIN_TEST_TOKEN"), "private-token")


if __name__ == "__main__":
    unittest.main()
