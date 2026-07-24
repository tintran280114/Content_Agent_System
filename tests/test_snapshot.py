from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from content_agent.platform import SQLiteRunStore
from content_agent.snapshot import install_sqlite_snapshot


class SnapshotTests(unittest.TestCase):
    def test_valid_store_backup_is_installed_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = SQLiteRunStore(root / "source.sqlite3")
            target = root / "target.sqlite3"

            install_sqlite_snapshot(source.backup_bytes(), target)

            connection = sqlite3.connect(target)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()
            self.assertIn("runs", tables)
            self.assertIn("workflow_items", tables)

    def test_invalid_upload_does_not_replace_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.sqlite3"
            original = SQLiteRunStore(target).backup_bytes()
            target.write_bytes(original)

            with self.assertRaisesRegex(ValueError, "valid SQLite"):
                install_sqlite_snapshot(b"not a database", target)

            self.assertEqual(target.read_bytes(), original)

    def test_unrelated_sqlite_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "unrelated.sqlite3"
            connection = sqlite3.connect(source)
            try:
                connection.execute("CREATE TABLE unrelated(value TEXT)")
                connection.commit()
            finally:
                connection.close()

            with self.assertRaisesRegex(ValueError, "missing required tables"):
                install_sqlite_snapshot(source.read_bytes(), root / "target.sqlite3")


if __name__ == "__main__":
    unittest.main()
