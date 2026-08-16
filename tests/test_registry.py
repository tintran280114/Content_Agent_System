from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401
from content_agent.ai.config import DEFAULT_ROUTES, Role
from content_agent.ai.registry import create_role_provider


class RegistryTests(unittest.TestCase):
    def test_copywriter_and_critic_use_distinct_models(self) -> None:
        self.assertEqual(DEFAULT_ROUTES[Role.COPYWRITER].provider, "groq")
        self.assertEqual(DEFAULT_ROUTES[Role.CRITIC].provider, "groq")
        self.assertNotEqual(
            DEFAULT_ROUTES[Role.COPYWRITER].primary_model,
            DEFAULT_ROUTES[Role.CRITIC].primary_model,
        )

    def test_copywriter_default_avoids_announced_groq_shutdown(self) -> None:
        self.assertEqual(
            DEFAULT_ROUTES[Role.COPYWRITER].primary_model,
            "openai/gpt-oss-120b",
        )

    def test_all_routes_have_fallbacks_and_credentials(self) -> None:
        for role, route in DEFAULT_ROUTES.items():
            with self.subTest(role=role.value):
                self.assertTrue(route.fallback_models)
                self.assertTrue(route.credential_env)
                self.assertIn("free", route.free_tier_note.lower())

    def test_environment_can_override_primary_model(self) -> None:
        route = DEFAULT_ROUTES[Role.CRITIC]
        self.assertEqual(
            route.selected_model({"GROQ_CRITIC_MODEL": "qwen/custom"}),
            "qwen/custom",
        )

    def test_policy_can_select_provider_and_model_without_code_change(self) -> None:
        provider = create_role_provider(
            Role.RESEARCH,
            provider="groq",
            model="openai/gpt-oss-120b",
            env={"GROQ_API_KEY": "test-only"},
        )
        self.assertEqual(provider.provider_name, "groq")
        self.assertEqual(provider.model, "openai/gpt-oss-120b")


if __name__ == "__main__":
    unittest.main()
