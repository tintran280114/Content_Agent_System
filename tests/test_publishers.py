from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import _bootstrap  # noqa: F401
from content_agent.ai.models import DraftPost, GenerationMetadata, TokenUsage
from content_agent.critics import render_post
from content_agent.platform import SQLiteRunStore
from content_agent.policy import parse_policy_text
from content_agent.publisher import (
    FacebookPagePublisher,
    LinkedInPublisher,
    MockPublisher,
    PolicyPublisherRouter,
    PublishError,
    ThreadsPublisher,
)
from content_agent.workflow import DraftOrigin, PublishStatus, WorkflowState


def policy_text(
    adapter: str,
    credential_ref: str,
    target_id: str,
    publishing_extra: str = "",
) -> str:
    if adapter != "mock":
        return f"""# Account Policy: delivery-test

## Account
- account_id: delivery-test
- spec_version: 0.2
- active: true

## Goal
Publish useful test content through a guarded delivery adapter.

## Audience
Software teams testing social automation.

## Platform
Meta

## Tone
Clear and practical.

## Language
English

## Constraints
- Keep the post concise.

## Examples
- A safe publisher separates account policy from access tokens.
- Dry-run every new target before enabling live delivery.

## Rubric
- policy_compliance: 60
- clarity: 40

## Threshold
80

## Maximum Length
500

## Model Route
- research: gemini@gemini-test
- copywriter: groq@groq-test
- critic: github_models@github-test

## Publishing
- adapter: {adapter}
- target_id: {target_id}
- credential_ref: {credential_ref}
- approval_required: false
{publishing_extra}
"""

    return f"""# Account Policy: delivery-test

## Account
- account_id: delivery-test
- spec_version: 0.2
- active: true

## Goal
Publish useful test content through a guarded delivery adapter.

## Audience
Software teams testing social automation.

## Platform
Meta

## Tone
Clear and practical.

## Language
English

## Constraints
- Keep the post concise.

## Examples
- A safe publisher separates account policy from access tokens.
- Dry-run every new target before enabling live delivery.

## Rubric
- policy_compliance: 60
- clarity: 40

## Threshold
80

## Maximum Length
500

## Model Route
- research: gemini@gemini-test
- copywriter: groq@groq-test
- critic: github_models@github-test

## Publishing
- adapter: mock
- approval_required: false
{publishing_extra}
"""


class FakeResponse:
    def __init__(self, status_code: int, payload: dict, *, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(
        self,
        responses: list[FakeResponse],
        *,
        get_responses: list[FakeResponse] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.get_responses = list(get_responses or [])
        self.get_calls: list[dict] = []

    def post(self, url: str, *, data=None, json=None, headers, timeout: float) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "data": dict(data) if data is not None else None,
                "json": dict(json) if json is not None else None,
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)

    def get(self, url: str, *, params, headers, timeout: float) -> FakeResponse:
        self.get_calls.append(
            {
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return self.get_responses.pop(0)


class PublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store = SQLiteRunStore(Path(self.tempdir.name) / "publisher.sqlite3")

    def create_publishable_run(
        self,
        *,
        adapter: str,
        credential_ref: str,
        target_id: str,
        publishing_extra: str = "",
    ):
        policy = parse_policy_text(
            policy_text(adapter, credential_ref, target_id, publishing_extra),
            source=f"{adapter}.md",
        )
        run_id = uuid4()
        draft = DraftPost(
            brief_id=uuid4(),
            topic="Safe social publishing",
            account_id=policy.account_id,
            platform=policy.platform,
            content="Ship through an audited outbox, not from an LLM callback.",
            hashtags=["#SafeAutomation"],
            call_to_action="Review before enabling live delivery.",
            policy_constraints_applied=["Keep the post concise."],
            metadata=GenerationMetadata(
                provider="groq",
                model="groq-test",
                role="copywriter",
                prompt_version="test",
                provider_sdk="fake/1",
                latency_ms=1,
                usage=TokenUsage(),
            ),
        )
        self.store.start_run(
            run_id=run_id,
            topic=draft.topic,
            policy=policy,
            source_path=f"{adapter}.md",
        )
        self.store.save_draft_revision(
            run_id=run_id,
            draft=draft,
            revision=0,
            origin=DraftOrigin.INITIAL_AI.value,
        )
        self.store.create_workflow(
            run_id=run_id,
            current_draft_id=draft.draft_id,
            state=WorkflowState.PASSED.value,
        )
        return run_id, draft

    def test_facebook_live_uses_bearer_token_and_is_idempotent(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="facebook_page",
            credential_ref="FACEBOOK_TEST_TOKEN",
            target_id="123456789",
        )
        client = FakeClient(
            [FakeResponse(200, {"id": "123456789_42"})],
            get_responses=[FakeResponse(200, {"id": "123456789", "name": "Test Page"})],
        )
        publisher = FacebookPagePublisher(
            self.store,
            mode="live",
            client=client,
            env={
                "FACEBOOK_TEST_TOKEN": "private-token",
                "META_GRAPH_API_VERSION": "v25.0",
            },
            sleeper=lambda _: None,
        )

        receipt = publisher.publish(run_id)
        repeated = publisher.publish(run_id)

        self.assertEqual(receipt.status, PublishStatus.PUBLISHED)
        self.assertEqual(receipt.remote_post_id, "123456789_42")
        self.assertEqual(receipt.publish_id, repeated.publish_id)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertTrue(call["url"].endswith("/v25.0/123456789/feed"))
        self.assertEqual(call["headers"]["Authorization"], "Bearer private-token")
        self.assertNotIn("private-token", call["url"])
        self.assertNotIn("access_token", call["data"])
        self.assertEqual(self.store.get_workflow(run_id)["state"], "published")

    def test_facebook_dry_run_needs_no_secret_and_makes_no_request(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="facebook_page",
            credential_ref="FACEBOOK_MISSING_TOKEN",
            target_id="123456789",
        )
        client = FakeClient([])

        receipt = FacebookPagePublisher(
            self.store,
            mode="dry-run",
            client=client,
            env={},
        ).publish(run_id)

        self.assertEqual(receipt.status, PublishStatus.DRY_RUN)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.store.get_workflow(run_id)["state"], "dry_run")

    def test_facebook_live_rejects_a_user_token_before_posting(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="facebook_page",
            credential_ref="FACEBOOK_TEST_TOKEN",
            target_id="123456789",
        )
        client = FakeClient(
            [],
            get_responses=[FakeResponse(200, {"id": "999999999", "name": "Test User"})],
        )

        with self.assertRaises(PublishError) as caught:
            FacebookPagePublisher(
                self.store,
                mode="live",
                client=client,
                env={"FACEBOOK_TEST_TOKEN": "user-token"},
            ).publish(run_id)

        self.assertEqual(caught.exception.code, "facebook_page_token_required")
        self.assertEqual(client.calls, [])
        self.assertNotIn("user-token", str(caught.exception))

    def test_facebook_live_can_follow_an_idempotent_dry_run(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="facebook_page",
            credential_ref="FACEBOOK_TEST_TOKEN",
            target_id="123456789",
        )
        dry_client = FakeClient([])
        dry_publisher = FacebookPagePublisher(
            self.store,
            mode="dry-run",
            client=dry_client,
            env={"META_GRAPH_API_VERSION": "v25.0"},
        )

        dry_receipt = dry_publisher.publish(run_id)
        repeated_dry_receipt = dry_publisher.publish(run_id)
        live_client = FakeClient(
            [FakeResponse(200, {"id": "123456789_44"})],
            get_responses=[FakeResponse(200, {"id": "123456789", "name": "Test Page"})],
        )
        live_receipt = FacebookPagePublisher(
            self.store,
            mode="live",
            client=live_client,
            env={
                "FACEBOOK_TEST_TOKEN": "private-token",
                "META_GRAPH_API_VERSION": "v25.0",
            },
            sleeper=lambda _: None,
        ).publish(run_id)

        self.assertEqual(dry_receipt.publish_id, repeated_dry_receipt.publish_id)
        self.assertNotEqual(dry_receipt.idempotency_key, live_receipt.idempotency_key)
        self.assertEqual(live_receipt.status, PublishStatus.PUBLISHED)
        self.assertEqual(len(live_client.calls), 1)
        self.assertEqual(self.store.get_workflow(run_id)["state"], "published")

    def test_dry_run_rejects_an_invalid_graph_version_without_calling_http(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="facebook_page",
            credential_ref="FACEBOOK_MISSING_TOKEN",
            target_id="123456789",
        )
        client = FakeClient([])

        with self.assertRaises(PublishError) as caught:
            FacebookPagePublisher(
                self.store,
                mode="dry-run",
                client=client,
                env={"META_GRAPH_API_VERSION": "latest"},
            ).publish(run_id)

        self.assertEqual(caught.exception.code, "invalid_graph_version")
        self.assertEqual(client.calls, [])
        self.assertEqual(self.store.get_publish_attempts(run_id)[0]["status"], "failed")

    def test_threads_live_uses_container_then_publish(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="threads",
            credential_ref="THREADS_TEST_TOKEN",
            target_id="987654321",
        )
        client = FakeClient(
            [
                FakeResponse(200, {"id": "container-1"}),
                FakeResponse(200, {"id": "thread-42"}),
            ]
        )
        receipt = ThreadsPublisher(
            self.store,
            mode="live",
            client=client,
            env={
                "THREADS_TEST_TOKEN": "threads-private-token",
                "THREADS_GRAPH_API_VERSION": "v1.0",
            },
            sleeper=lambda _: None,
        ).publish(run_id)

        self.assertEqual(receipt.status, PublishStatus.PUBLISHED)
        self.assertEqual(receipt.remote_post_id, "thread-42")
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(client.calls[0]["url"].endswith("/987654321/threads"))
        self.assertEqual(client.calls[0]["data"]["media_type"], "TEXT")
        self.assertTrue(client.calls[1]["url"].endswith("/987654321/threads_publish"))
        self.assertEqual(client.calls[1]["data"]["creation_id"], "container-1")

    def test_threads_live_silently_refreshes_near_expiry(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="threads",
            credential_ref="THREADS_TEST_TOKEN",
            target_id="987654321",
        )
        client = FakeClient(
            [
                FakeResponse(200, {"id": "container-refreshed"}),
                FakeResponse(200, {"id": "thread-refreshed"}),
            ],
            get_responses=[
                FakeResponse(
                    200,
                    {
                        "access_token": "rotated-private-token",
                        "expires_in": 5_184_000,
                    },
                )
            ],
        )
        expiry = (datetime.now(UTC) + timedelta(days=2)).isoformat()

        receipt = ThreadsPublisher(
            self.store,
            mode="live",
            client=client,
            env={
                "THREADS_TEST_TOKEN": "old-private-token",
                "THREADS_TEST_TOKEN_EXPIRES_AT": expiry,
                "THREADS_GRAPH_API_VERSION": "v1.0",
            },
            sleeper=lambda _: None,
        ).publish(run_id)

        self.assertEqual(receipt.remote_post_id, "thread-refreshed")
        self.assertEqual(len(client.get_calls), 1)
        self.assertTrue(client.get_calls[0]["url"].endswith("/refresh_access_token"))
        self.assertEqual(
            client.calls[0]["headers"]["Authorization"],
            "Bearer rotated-private-token",
        )

    def test_threads_selects_most_active_configured_topic_tag(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="threads",
            credential_ref="THREADS_TEST_TOKEN",
            target_id="987654321",
            publishing_extra=(
                "- topic_tag: Responsible AI\n"
                "- topic_tag_candidates: Responsible AI | AI Tools | AI for Business\n"
                "- trend_search: true"
            ),
        )
        client = FakeClient(
            [
                FakeResponse(200, {"id": "container-2"}),
                FakeResponse(200, {"id": "thread-43"}),
            ],
            get_responses=[
                FakeResponse(200, {"data": [{"id": "1"}]}),
                FakeResponse(200, {"data": [{"id": "2"}, {"id": "3"}, {"id": "4"}]}),
                FakeResponse(200, {"data": []}),
            ],
        )

        receipt = ThreadsPublisher(
            self.store,
            mode="live",
            client=client,
            env={
                "THREADS_TEST_TOKEN": "threads-private-token",
                "THREADS_GRAPH_API_VERSION": "v1.0",
            },
            sleeper=lambda _: None,
        ).publish(run_id)

        self.assertEqual(receipt.topic_tag, "AI Tools")
        self.assertEqual(receipt.attempt_count, 5)
        self.assertEqual(len(client.get_calls), 3)
        self.assertTrue(client.get_calls[0]["url"].endswith("/v1.0/keyword_search"))
        self.assertEqual(client.get_calls[0]["params"]["search_mode"], "TAG")
        self.assertEqual(client.get_calls[0]["params"]["search_type"], "RECENT")
        self.assertEqual(
            client.get_calls[0]["headers"]["Authorization"],
            "Bearer threads-private-token",
        )
        self.assertEqual(client.calls[0]["data"]["topic_tag"], "AI Tools")

    def test_threads_dry_run_uses_fallback_topic_without_searching(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="threads",
            credential_ref="THREADS_MISSING_TOKEN",
            target_id="987654321",
            publishing_extra=(
                "- topic_tag: Responsible AI\n"
                "- topic_tag_candidates: Responsible AI | AI Tools\n"
                "- trend_search: true"
            ),
        )
        client = FakeClient([])

        receipt = ThreadsPublisher(
            self.store,
            mode="dry-run",
            client=client,
            env={},
        ).publish(run_id)

        self.assertEqual(receipt.status, PublishStatus.DRY_RUN)
        self.assertEqual(receipt.topic_tag, "Responsible AI")
        self.assertEqual(client.calls, [])
        self.assertEqual(client.get_calls, [])

    def test_linkedin_dry_run_needs_no_secret_and_makes_no_request(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="linkedin",
            credential_ref="LINKEDIN_MISSING_TOKEN",
            target_id="urn:li:person:123456789",
        )
        client = FakeClient([])

        receipt = LinkedInPublisher(
            self.store,
            mode="dry-run",
            client=client,
            env={},
        ).publish(run_id)

        self.assertEqual(receipt.status, PublishStatus.DRY_RUN)
        self.assertEqual(client.calls, [])

    def test_linkedin_live_posts_json_retries_and_is_idempotent(self) -> None:
        run_id, draft = self.create_publishable_run(
            adapter="linkedin",
            credential_ref="LINKEDIN_TEST_TOKEN",
            target_id="urn:li:person:123456789",
        )
        sleeps: list[float] = []
        client = FakeClient(
            [
                FakeResponse(429, {"message": "hidden"}),
                FakeResponse(
                    201,
                    {},
                    headers={"x-restli-id": "urn:li:share:987654321"},
                ),
            ]
        )
        publisher = LinkedInPublisher(
            self.store,
            mode="live",
            client=client,
            env={
                "LINKEDIN_TEST_TOKEN": "linkedin-private-token",
            },
            base_backoff_seconds=0.25,
            sleeper=sleeps.append,
        )

        receipt = publisher.publish(run_id)
        repeated = publisher.publish(run_id)

        self.assertEqual(receipt.publish_id, repeated.publish_id)
        self.assertEqual(receipt.remote_post_id, "urn:li:share:987654321")
        self.assertEqual(receipt.attempt_count, 2)
        self.assertEqual(sleeps, [0.25])
        self.assertEqual(len(client.calls), 2)
        call = client.calls[1]
        self.assertEqual(call["url"], "https://api.linkedin.com/rest/posts")
        self.assertEqual(call["headers"]["Authorization"], "Bearer linkedin-private-token")
        self.assertEqual(call["headers"]["X-Restli-Protocol-Version"], "2.0.0")
        self.assertEqual(call["headers"]["Linkedin-Version"], "202604")
        self.assertEqual(call["json"]["author"], "urn:li:person:123456789")
        self.assertEqual(call["json"]["commentary"], render_post(draft))
        self.assertEqual(call["json"]["visibility"], "PUBLIC")
        self.assertEqual(call["json"]["distribution"]["feedDistribution"], "MAIN_FEED")
        self.assertEqual(call["json"]["distribution"]["targetEntities"], [])
        self.assertEqual(call["json"]["distribution"]["thirdPartyDistributionChannels"], [])
        self.assertFalse(call["json"]["isReshareDisabledByAuthor"])
        self.assertNotIn("linkedin-private-token", str(call["json"]))

    def test_router_selects_linkedin_and_keeps_auth_error_safe(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="linkedin",
            credential_ref="LINKEDIN_TEST_TOKEN",
            target_id="urn:li:person:123456789",
        )
        client = FakeClient([FakeResponse(401, {"message": "secret details"})])

        with self.assertRaises(PublishError) as caught:
            PolicyPublisherRouter(
                self.store,
                mode="live",
                client=client,
                env={"LINKEDIN_TEST_TOKEN": "linkedin-private-token"},
                sleeper=lambda _: None,
            ).publish(run_id)

        self.assertEqual(caught.exception.code, "publish_authentication")
        self.assertNotIn("linkedin-private-token", str(caught.exception))
        self.assertNotIn("secret details", str(caught.exception))
        self.assertEqual(self.store.get_publish_attempts(run_id)[0]["status"], "failed")

    def test_linkedin_posts_access_denial_explains_oauth_is_not_the_fix(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="linkedin",
            credential_ref="LINKEDIN_TEST_TOKEN",
            target_id="urn:li:person:123456789",
        )
        with self.assertRaises(PublishError) as caught:
            LinkedInPublisher(
                self.store,
                mode="live",
                client=FakeClient([FakeResponse(403, {"message": "raw provider details"})]),
                env={"LINKEDIN_TEST_TOKEN": "linkedin-private-token"},
                sleeper=lambda _: None,
            ).publish(run_id)

        self.assertEqual(caught.exception.code, "linkedin_posts_api_access_denied")
        self.assertIn("OAuth connected successfully", str(caught.exception))
        self.assertIn("w_member_social", str(caught.exception))
        self.assertNotIn("linkedin-private-token", str(caught.exception))
        self.assertNotIn("raw provider details", str(caught.exception))

    def test_rate_limit_retries_without_consuming_content_rewrite_budget(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="facebook_page",
            credential_ref="FACEBOOK_TEST_TOKEN",
            target_id="123456789",
        )
        sleeps: list[float] = []
        client = FakeClient(
            [
                FakeResponse(429, {"error": {"message": "hidden"}}),
                FakeResponse(200, {"id": "123456789_43"}),
            ],
            get_responses=[FakeResponse(200, {"id": "123456789", "name": "Test Page"})],
        )
        receipt = FacebookPagePublisher(
            self.store,
            mode="live",
            client=client,
            env={"FACEBOOK_TEST_TOKEN": "private-token"},
            base_backoff_seconds=0.25,
            sleeper=sleeps.append,
        ).publish(run_id)

        self.assertEqual(receipt.attempt_count, 2)
        self.assertEqual(sleeps, [0.25])
        self.assertEqual(self.store.get_workflow(run_id)["rewrite_count"], 0)

    def test_missing_secret_is_recorded_as_failed_without_leaking_value(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="facebook_page",
            credential_ref="FACEBOOK_MISSING_TOKEN",
            target_id="123456789",
        )
        publisher = FacebookPagePublisher(
            self.store,
            mode="live",
            client=FakeClient([]),
            env={},
        )

        with self.assertRaises(PublishError) as caught:
            publisher.publish(run_id)

        self.assertEqual(caught.exception.code, "missing_publish_credential")
        attempts = self.store.get_publish_attempts(run_id)
        self.assertEqual(attempts[0]["status"], "failed")
        self.assertNotIn("Bearer", str(attempts))

    def test_expired_or_unauthorized_token_has_safe_actionable_error(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="facebook_page",
            credential_ref="FACEBOOK_TEST_TOKEN",
            target_id="123456789",
        )
        publisher = FacebookPagePublisher(
            self.store,
            mode="live",
            client=FakeClient(
                [],
                get_responses=[FakeResponse(401, {"error": {"message": "secret details"}})],
            ),
            env={"FACEBOOK_TEST_TOKEN": "expired-private-token"},
            sleeper=lambda _: None,
        )

        with self.assertRaises(PublishError) as caught:
            publisher.publish(run_id)

        self.assertEqual(caught.exception.code, "publish_authentication")
        self.assertEqual(caught.exception.status_code, 401)
        self.assertNotIn("expired-private-token", str(caught.exception))
        self.assertNotIn("secret details", str(caught.exception))
        attempt = self.store.get_publish_attempts(run_id)[0]
        self.assertEqual(attempt["status"], "failed")
        self.assertEqual(attempt["http_status"], 401)

    def test_meta_parameter_error_keeps_numeric_diagnostics_without_body(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="facebook_page",
            credential_ref="FACEBOOK_TEST_TOKEN",
            target_id="123456789",
        )
        publisher = FacebookPagePublisher(
            self.store,
            mode="live",
            client=FakeClient(
                [
                    FakeResponse(
                        400,
                        {
                            "error": {
                                "message": "raw provider detail must not be exposed",
                                "code": 100,
                                "error_subcode": 42,
                            }
                        },
                    )
                ],
                get_responses=[FakeResponse(200, {"id": "123456789", "name": "Test Page"})],
            ),
            env={"FACEBOOK_TEST_TOKEN": "private-token"},
            sleeper=lambda _: None,
        )

        with self.assertRaises(PublishError) as caught:
            publisher.publish(run_id)

        self.assertIn("publishing parameter", str(caught.exception))
        self.assertIn("Meta code 100, subcode 42", str(caught.exception))
        self.assertNotIn("raw provider detail", str(caught.exception))


    def test_mock_publisher_validates_and_publishes(self) -> None:
        run_id, _ = self.create_publishable_run(
            adapter="mock",
            credential_ref="MOCK_TOKEN",
            target_id="mock_target",
        )
        publisher = MockPublisher(self.store)
        receipt = publisher.publish(run_id)
        self.assertEqual(receipt.status, PublishStatus.PUBLISHED)
        self.assertIsNone(receipt.topic_tag)


if __name__ == "__main__":
    unittest.main()
