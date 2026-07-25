from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from pydantic import ValidationError

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "provider_spike.py"
SPEC = importlib.util.spec_from_file_location("provider_spike", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load provider_spike.py")
provider_spike = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provider_spike)


class ProviderSpikeTests(unittest.TestCase):
    def test_github_smoke_payload_requires_expected_json_shape(self) -> None:
        payload = provider_spike.GitHubSmokePayload.model_validate(
            {"caption": "Launch day", "hashtags": ["#Productivity"], "cta": "Try it"}
        )
        self.assertEqual(payload.hashtags, ["#Productivity"])

        with self.assertRaises(ValidationError):
            provider_spike.GitHubSmokePayload.model_validate(
                {"caption": "Launch day", "hashtags": "#Productivity", "cta": "Try it"}
            )


if __name__ == "__main__":
    unittest.main()
