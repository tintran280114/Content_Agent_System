from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import _bootstrap  # noqa: F401

import run as run_module
from content_agent.orchestrator import PipelineRunError
from content_agent.platform import RunStep

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "run.py"


class CliTests(unittest.TestCase):
    def test_help_works_without_credentials(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(RUN), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--account", completed.stdout)
        self.assertIn("--all", completed.stdout)
        self.assertIn("--pipeline", completed.stdout)
        self.assertIn("--database", completed.stdout)
        self.assertIn("Default: full", completed.stdout)
        self.assertIn("artifacts/content_agent.sqlite3", completed.stdout.replace("\\", "/"))

    def test_list_accounts_validates_all_three_policies(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(RUN), "--list-accounts"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)
        self.assertTrue(any("responsible-ai-lab" in line for line in lines))

    def test_missing_policy_has_actionable_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUN),
                    "--account",
                    "does-not-exist",
                    "--accounts-dir",
                    directory,
                    "--database",
                    str(Path(directory) / "unused.sqlite3"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("Policy error", completed.stderr)
        self.assertIn("does not exist", completed.stderr)

    def test_all_accounts_stops_immediately_when_quota_is_exhausted(self) -> None:
        calls: list[str] = []

        class QuotaPipeline:
            def __init__(self, store) -> None:
                self.store = store

            def run(self, *, topic: str, policy_path: Path, mode) -> None:
                calls.append(policy_path.name)
                raise PipelineRunError(
                    uuid4(),
                    RunStep.RESEARCH,
                    "quota_exhausted",
                    "Application daily quota was exhausted.",
                )

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(run_module, "PipelineOrchestrator", QuotaPipeline):
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    exit_code = run_module.main(
                        [
                            "--all",
                            "--accounts-dir",
                            str(ROOT / "accounts"),
                            "--database",
                            str(Path(directory) / "quota.sqlite3"),
                        ]
                    )

        self.assertEqual(exit_code, 4)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
