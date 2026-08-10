from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet

import _bootstrap  # noqa: F401
from content_agent.meta_auth import (
    EncryptedTokenStore,
    MetaAuthError,
    ThreadsOAuthClient,
    ThreadsTokenManager,
    build_threads_authorization_url,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(self, *, gets: list[FakeResponse] | None = None, posts=None) -> None:
        self.gets = list(gets or [])
        self.posts = list(posts or [])
        self.get_calls: list[dict] = []
        self.post_calls: list[dict] = []

    def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return self.gets.pop(0)

    def post(self, url: str, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        return self.posts.pop(0)


class MetaAuthTests(unittest.TestCase):
    def test_encrypted_store_never_writes_plaintext_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tokens.enc"
            store = EncryptedTokenStore(path, Fernet.generate_key())
            now = datetime(2026, 7, 29, tzinfo=UTC)
            manager = ThreadsTokenManager(
                env={},
                store=store,
                now=lambda: now,
            )
            manager.save_long_lived_token(
                "THREADS_TEST_TOKEN",
                access_token="private-long-lived-token",
                expires_in=5_184_000,
                user_id="123",
            )

            self.assertTrue(path.exists())
            self.assertNotIn(b"private-long-lived-token", path.read_bytes())
            loaded = ThreadsTokenManager(
                env={},
                store=store,
                now=lambda: now,
            ).status("THREADS_TEST_TOKEN")
            self.assertTrue(loaded.configured)
            self.assertEqual(loaded.source, "encrypted_store")

    def test_resolve_silently_refreshes_inside_window_and_persists_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 7, 29, tzinfo=UTC)
            store = EncryptedTokenStore(
                Path(directory) / "tokens.enc",
                Fernet.generate_key(),
            )
            seed = ThreadsTokenManager(env={}, store=store, now=lambda: now)
            seed.save_long_lived_token(
                "THREADS_TEST_TOKEN",
                access_token="old-token",
                expires_in=2 * 24 * 60 * 60,
            )
            client = FakeClient(
                gets=[
                    FakeResponse(
                        200,
                        {
                            "access_token": "rotated-token",
                            "expires_in": 5_184_000,
                        },
                    )
                ]
            )
            manager = ThreadsTokenManager(
                env={},
                store=store,
                client=client,
                now=lambda: now + timedelta(hours=1),
            )

            self.assertEqual(manager.resolve("THREADS_TEST_TOKEN"), "rotated-token")
            self.assertEqual(len(client.get_calls), 1)
            self.assertEqual(
                client.get_calls[0]["params"]["grant_type"],
                "th_refresh_token",
            )
            self.assertEqual(
                client.get_calls[0]["headers"]["Authorization"],
                "Bearer old-token",
            )
            encrypted_bytes = store.path.read_bytes()
            self.assertNotIn(b"rotated-token", encrypted_bytes)

    def test_expired_token_requires_reconnect(self) -> None:
        now = datetime(2026, 7, 29, tzinfo=UTC)
        manager = ThreadsTokenManager(
            env={
                "THREADS_TEST_TOKEN": "expired",
                "THREADS_TEST_TOKEN_EXPIRES_AT": (now - timedelta(seconds=1)).isoformat(),
            },
            now=lambda: now,
        )
        with self.assertRaisesRegex(MetaAuthError, "reconnect"):
            manager.resolve("THREADS_TEST_TOKEN")

    def test_oauth_exchange_uses_code_then_long_lived_token(self) -> None:
        client = FakeClient(
            posts=[FakeResponse(200, {"access_token": "short", "user_id": "987"})],
            gets=[
                FakeResponse(
                    200,
                    {"access_token": "long", "expires_in": 5_184_000},
                )
            ],
        )
        token, user_id, expires_in = ThreadsOAuthClient(client=client).exchange_code(
            code="code",
            app_id="app",
            app_secret="secret",
            redirect_uri="http://localhost:8501",
        )

        self.assertEqual((token, user_id, expires_in), ("long", "987", 5_184_000))
        self.assertNotIn("secret", client.post_calls[0]["url"])
        self.assertNotIn("params", client.post_calls[0])
        self.assertEqual(
            client.post_calls[0]["data"],
            {
                "client_id": "app",
                "client_secret": "secret",
                "code": "code",
                "grant_type": "authorization_code",
                "redirect_uri": "http://localhost:8501",
            },
        )
        self.assertEqual(
            client.get_calls[0]["params"],
            {
                "grant_type": "th_exchange_token",
                "client_secret": "secret",
                "access_token": "short",
            },
        )
        self.assertNotIn("Authorization", client.get_calls[0]["headers"])

    def test_authorization_url_has_scopes_state_and_no_secret(self) -> None:
        url = build_threads_authorization_url(
            app_id="app-id",
            redirect_uri="http://localhost:8501",
            state="csrf-state",
            include_keyword_search=True,
        )
        self.assertIn("threads_basic", url)
        self.assertIn("threads_content_publish", url)
        self.assertIn("threads_keyword_search", url)
        self.assertIn("csrf-state", url)
        self.assertNotIn("secret", url)


if __name__ == "__main__":
    unittest.main()
