from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
        self.assertIn("--database", completed.stdout)

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


if __name__ == "__main__":
    unittest.main()
