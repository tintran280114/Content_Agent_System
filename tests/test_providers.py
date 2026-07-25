from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401
from content_agent.ai.base import ChatMessage
from content_agent.ai.errors import ErrorCode, ProviderError
from content_agent.ai.models import DraftPayload, ResearchPayload
from content_agent.ai.providers import GeminiProvider, GitHubModelsProvider, GroqProvider

RESEARCH = {
    "summary": "A sufficiently detailed structured response for adapter testing.",
    "key_points": ["One", "Two"],
    "audience_insights": ["Insight"],
    "content_angles": ["Angle"],
    "risks": [],
    "source_notes": ["Fixture"],
}

DRAFT = {
    "content": "A concise test post.",
    "hashtags": ["#Test"],
    "call_to_action": "Try it.",
    "policy_constraints_applied": ["Be concise"],
}


class FakeCompletions:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="request-1",
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.payload)))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        )


class FakeOpenAIClient:
    def __init__(self, payload: dict) -> None:
        self.completions = FakeCompletions(payload)
        self.chat = SimpleNamespace(completions=self.completions)


class FakeGeminiModels:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            text=json.dumps(self.payload),
            response_id="request-2",
            usage_metadata=SimpleNamespace(
                prompt_token_count=15,
                candidates_token_count=9,
                total_token_count=24,
            ),
        )


class ProviderAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.messages = [ChatMessage(role="user", content="Return JSON")]

    def test_gemini_validates_and_collects_usage(self) -> None:
        fake_models = FakeGeminiModels(RESEARCH)
        provider = GeminiProvider(
            api_key=None,
            model="gemini-test",
            client=SimpleNamespace(models=fake_models),
        )
        response = provider.generate(
            messages=self.messages,
            response_model=ResearchPayload,
            role="research",
            prompt_version="test-v1",
        )
        self.assertEqual(response.metadata.usage.total_tokens, 24)
        self.assertEqual(response.metadata.provider, "gemini")
        self.assertIn("response_json_schema", fake_models.kwargs["config"].model_fields_set)

    def test_groq_gpt_oss_requests_strict_json_schema(self) -> None:
        fake = FakeOpenAIClient(DRAFT)
        provider = GroqProvider(api_key=None, model="openai/gpt-oss-120b", client=fake)
        response = provider.generate(
            messages=self.messages,
            response_model=DraftPayload,
            role="copywriter",
            prompt_version="test-v1",
        )
        self.assertEqual(response.metadata.provider, "groq")
        response_format = fake.completions.kwargs["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        schema = response_format["json_schema"]["schema"]
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(fake.completions.kwargs["reasoning_effort"], "low")

    def test_groq_other_models_retain_json_object_fallback(self) -> None:
        fake = FakeOpenAIClient(DRAFT)
        provider = GroqProvider(api_key=None, model="groq-test", client=fake)
        response = provider.generate(
            messages=self.messages,
            response_model=DraftPayload,
            role="copywriter",
            prompt_version="test-v1",
        )
        self.assertEqual(response.metadata.provider, "groq")
        self.assertEqual(fake.completions.kwargs["response_format"], {"type": "json_object"})

    def test_github_models_requests_json_mode(self) -> None:
        fake = FakeOpenAIClient(DRAFT)
        provider = GitHubModelsProvider(api_key=None, model="openai/test", client=fake)
        response = provider.generate(
            messages=self.messages,
            response_model=DraftPayload,
            role="critic",
            prompt_version="test-v1",
        )
        self.assertEqual(response.metadata.provider, "github_models")
        self.assertEqual(fake.completions.kwargs["response_format"], {"type": "json_object"})

    def test_malformed_json_keeps_structured_error_code(self) -> None:
        fake = FakeOpenAIClient(DRAFT)
        fake.completions.payload = "not-json"

        def malformed(**kwargs):
            return SimpleNamespace(
                id="request-bad",
                choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))],
                usage=None,
            )

        fake.completions.create = malformed
        provider = GitHubModelsProvider(api_key=None, model="openai/test", client=fake)
        with self.assertRaises(ProviderError) as raised:
            provider.generate(
                messages=self.messages,
                response_model=DraftPayload,
                role="critic",
                prompt_version="test-v1",
            )
        self.assertEqual(raised.exception.code, ErrorCode.MALFORMED_RESPONSE)
        self.assertTrue(raised.exception.retryable)


if __name__ == "__main__":
    unittest.main()
