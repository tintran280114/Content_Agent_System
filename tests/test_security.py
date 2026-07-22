from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SecurityTests(unittest.TestCase):
    def test_no_provider_secret_is_present_in_shareable_files(self) -> None:
        patterns = [
            re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
            re.compile(r"gsk_[0-9A-Za-z]{20,}"),
            re.compile(r"github_pat_[0-9A-Za-z_]{40,}"),
            re.compile(r"ghp_[0-9A-Za-z]{30,}"),
        ]
        excluded = {".env", "secrets.toml", ".git", ".venv", "artifacts", "__pycache__"}
        findings: list[str] = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or any(part in excluded for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if any(pattern.search(text) for pattern in patterns):
                findings.append(str(path.relative_to(ROOT)))
        self.assertEqual(findings, [], f"Potential secrets found in: {findings}")


if __name__ == "__main__":
    unittest.main()
