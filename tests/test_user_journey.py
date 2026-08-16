from __future__ import annotations

import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import _bootstrap  # noqa: F401
from content_agent.ai.base import ChatMessage, ProviderResponse, SchemaT, StructuredProvider
from content_agent.ai.config import Role
from content_agent.ai.models import ContentRequest, GenerationMetadata, TokenUsage
from content_agent.orchestrator import PipelineOrchestrator
from content_agent.platform import SQLiteRunStore
from content_agent.policy_builder import (
    PolicyBuilderInput,
    render_policy_markdown,
    save_policy_markdown,
)
from content_agent.publisher import PolicyPublisherRouter
from content_agent.review import ReviewService
from content_agent.workflow import PublishStatus, WorkflowState


class JourneyProvider(StructuredProvider):
    def __init__(self, provider_name: str, response: dict) -> None:
        self.provider_name = provider_name
        self.model = f"{provider_name}-journey-test"
        self.response = response
        self.calls = 0
        self.last_messages: Sequence[ChatMessage] = []

    def generate(
        self,
        *,
        messages: Sequence[ChatMessage],
        response_model: type[SchemaT],
        role: Literal["research", "copywriter", "critic"],
        prompt_version: str,
    ) -> ProviderResponse[SchemaT]:
        self.calls += 1
        self.last_messages = messages
        return ProviderResponse(
            output=response_model.model_validate(self.response),
            metadata=GenerationMetadata(
                provider=self.provider_name,
                model=self.model,
                role=role,
                prompt_version=prompt_version,
                provider_sdk="journey-fake/1",
                latency_ms=1,
                usage=TokenUsage(input_tokens=12, output_tokens=8, total_tokens=20),
            ),
        )


class CompleteUserJourneyTests(unittest.TestCase):
    def test_policy_prompt_ai_review_approve_and_threads_dry_run(self) -> None:
        values = PolicyBuilderInput(
            display_name="Journey Threads Account",
            account_id="journey-threads",
            goal="Teach small teams a practical and responsible AI publishing workflow.",
            audience="Vietnamese founders and social content operators.",
            platform="Threads",
            tone="Practical, calm, concise, and trustworthy.",
            language="Vietnamese",
            constraints=[
                "Do not promise guaranteed results.",
                "Keep a human accountable for publication.",
            ],
            banned_terms=["guaranteed"],
            required_hashtags=["#ResponsibleAI"],
            examples=[
                "Bắt đầu nhỏ, kiểm tra kết quả và luôn có người chịu trách nhiệm.",
                "Bản nháp AI cần chính sách, bằng chứng và bước duyệt rõ ràng.",
            ],
            adapter="threads",
            target_id="123456789",
            credential_ref="THREADS_JOURNEY_TOKEN",
            approval_required=True,
            topic_tag="Responsible AI",
            topic_tag_candidates=["Responsible AI", "AI Tools"],
            trend_search=True,
        )
        research = {
            "summary": (
                "A practical brief about reviewing AI social content before it reaches "
                "a public Threads account."
            ),
            "key_points": ["Use written rules", "Keep a human approver"],
            "audience_insights": ["Small teams need a simple repeatable flow"],
            "content_angles": ["A three-step pre-publish checklist"],
            "risks": ["Unsupported claims"],
            "source_notes": ["No live web grounding in this deterministic test"],
        }
        draft = {
            "content": (
                "Trước khi đăng bài AI: kiểm tra tuyên bố, đối chiếu policy và chỉ định "
                "một người chịu trách nhiệm cuối cùng."
            ),
            "hashtags": ["#ResponsibleAI"],
            "call_to_action": "Đội của bạn đang thiếu bước kiểm tra nào?",
            "policy_constraints_applied": [
                "Do not promise guaranteed results.",
                "Keep a human accountable for publication.",
            ],
        }
        critic = {
            "rule_passed": True,
            "score": 92,
            "violations": [],
            "suggestions": ["Keep the checklist concrete."],
            "decision": "pass",
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path, _ = save_policy_markdown(
                render_policy_markdown(values),
                root / "accounts",
            )
            store = SQLiteRunStore(root / "journey.sqlite3")
            providers = {
                Role.RESEARCH: JourneyProvider("gemini", research),
                Role.COPYWRITER: JourneyProvider("groq", draft),
                Role.CRITIC: JourneyProvider("groq", critic),
            }
            request = ContentRequest.from_inputs(
                topic="Kiểm duyệt nội dung AI trước khi đăng",
                instructions="Chuyển nội dung nguồn thành checklist ba bước và kết thúc bằng câu hỏi.",
                source_content=(
                    "Ghi chú nội bộ: kiểm tra tuyên bố, đối chiếu policy, sau đó "
                    "chỉ định một người chịu trách nhiệm cuối cùng."
                ),
                source_name="internal-note.md",
                task="repurpose",
            )
            result = PipelineOrchestrator(
                store,
                provider_factory=lambda role, **_: providers[role],
                publisher=PolicyPublisherRouter(store, mode="dry-run", env={}),
                sleeper=lambda _: None,
            ).run(
                request=request,
                policy_path=policy_path,
            )

            self.assertEqual(result.workflow_state, WorkflowState.HUMAN_REVIEW)
            self.assertEqual(result.critic.score, 92)
            self.assertEqual(result.request.request_id, request.request_id)
            self.assertEqual(store.get_content_request(result.run_id), request)
            self.assertEqual(result.research.request_id, request.request_id)
            self.assertEqual(result.draft.request_id, request.request_id)
            self.assertEqual(len(store.list_review_queue()), 1)
            self.assertEqual(
                {role.value: provider.calls for role, provider in providers.items()},
                {"research": 1, "copywriter": 1, "critic": 1},
            )
            for role, provider in providers.items():
                with self.subTest(role=role):
                    prompt = "\n".join(message.content for message in provider.last_messages)
                    self.assertIn("kiểm tra tuyên bố", prompt)
                    self.assertIn("checklist ba bước", prompt)

            ReviewService(store, publish_on_approve=False).approve(
                result.run_id,
                actor="boss@example.com",
                note="Reviewed claims, policy constraints, voice, and CTA.",
            )
            self.assertEqual(store.get_workflow(result.run_id)["state"], "approved")

            receipt = PolicyPublisherRouter(
                store,
                mode="dry-run",
                env={"THREADS_GRAPH_API_VERSION": "v1.0"},
            ).publish(result.run_id)

            self.assertEqual(receipt.status, PublishStatus.DRY_RUN)
            self.assertEqual(receipt.topic_tag, "Responsible AI")
            self.assertEqual(store.get_workflow(result.run_id)["state"], "dry_run")
            self.assertEqual(
                [action["action"] for action in store.get_review_actions(result.run_id)],
                ["approve"],
            )
            self.assertEqual(len(store.get_publish_attempts(result.run_id)), 1)
            self.assertEqual(store.usage_summary()["total"]["request_count"], 3)


if __name__ == "__main__":
    unittest.main()
