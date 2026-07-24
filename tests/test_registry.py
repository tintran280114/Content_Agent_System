from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from content_agent.ai.config import DEFAULT_ROUTES, Role


class RegistryTests(unittest.TestCase):
    def test_copywriter_and_critic_are_separate_providers(self) -> None:
        self.assertNotEqual(
            DEFAULT_ROUTES[Role.COPYWRITER].provider,
            DEFAULT_ROUTES[Role.CRITIC].provider,
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
            route.selected_model({"GITHUB_MODELS_MODEL": "openai/custom"}),
            "openai/custom",
        )


if __name__ == "__main__":
    unittest.main()
