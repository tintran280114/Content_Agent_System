from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from content_agent.platform import SQLiteRunStore


class StorageTests(unittest.TestCase):
    def test_internal_sqlite_enables_wal_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runtime.sqlite3"
            SQLiteRunStore(database)
            connection = sqlite3.connect(database)
            try:
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            finally:
                connection.close()
        self.assertEqual(journal_mode.casefold(), "wal")

    def test_sqlite_backup_contains_committed_wal_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SQLiteRunStore(root / "runtime.sqlite3")
            connection = sqlite3.connect(store.database_path)
            try:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('backup_marker', 'present')"
                )
                connection.commit()
            finally:
                connection.close()

            restored = root / "restored.sqlite3"
            restored.write_bytes(store.backup_bytes())
            connection = sqlite3.connect(restored)
            try:
                marker = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'backup_marker'"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(marker, "present")


if __name__ == "__main__":
    unittest.main()
