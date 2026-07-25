from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401
from content_agent.platform import SQLiteRunStore
from content_agent.snapshot import (
    install_sqlite_snapshot,
    save_rotating_snapshot,
    unique_snapshot_name,
)


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
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
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

    def test_cloud_import_rejects_an_empty_snapshot_without_replacing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = SQLiteRunStore(root / "empty.sqlite3")
            target = root / "target.sqlite3"
            target.write_bytes(b"existing-data")

            with self.assertRaisesRegex(ValueError, "contains 0 runs"):
                install_sqlite_snapshot(
                    source.backup_bytes(),
                    target,
                    require_runs=True,
                )

            self.assertEqual(target.read_bytes(), b"existing-data")

    def test_snapshot_names_are_randomized_and_collision_safe(self) -> None:
        names = {unique_snapshot_name() for _ in range(50)}

        self.assertEqual(len(names), 50)
        self.assertTrue(all(name.startswith("content-agent-") for name in names))
        self.assertTrue(all(name.endswith(".sqlite3") for name in names))

    def test_rotating_snapshots_retain_only_the_newest_twenty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = SQLiteRunStore(root / "canonical.sqlite3")
            snapshot_directory = root / "snapshots"
            created_names: set[str] = set()

            for _ in range(25):
                saved = save_rotating_snapshot(
                    canonical.backup_bytes(),
                    snapshot_directory,
                    limit=20,
                )
                created_names.add(saved.name)

            retained = list(snapshot_directory.glob("content-agent-*.sqlite3"))
            self.assertEqual(len(created_names), 25)
            self.assertEqual(len(retained), 20)
            self.assertTrue(canonical.database_path.exists())
            self.assertTrue(all(path.read_bytes().startswith(b"SQLite format 3\x00") for path in retained))

    def test_rotation_limit_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = SQLiteRunStore(Path(directory) / "source.sqlite3").backup_bytes()
            with self.assertRaisesRegex(ValueError, "between 1 and 100"):
                save_rotating_snapshot(data, Path(directory) / "snapshots", limit=0)


if __name__ == "__main__":
    unittest.main()
