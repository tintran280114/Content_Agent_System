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
                connection.execute("INSERT INTO schema_meta(key, value) VALUES('backup_marker', 'present')")
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

    def test_v02_publish_receipts_migrate_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TABLE runs (
                        run_id TEXT PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        state TEXT NOT NULL,
                        error_code TEXT,
                        error_message TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO runs(
                        run_id, account_id, topic, state, created_at, updated_at
                    ) VALUES(
                        'legacy-run', 'legacy-account', 'topic', 'completed',
                        '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
                    );
                    CREATE TABLE publish_attempts (
                        publish_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        draft_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    INSERT INTO publish_attempts(
                        publish_id, run_id, draft_id, status, reason,
                        payload_json, created_at
                    ) VALUES(
                        'legacy-publish', 'legacy-run', 'legacy-draft',
                        'published', 'legacy', '{}', '2026-01-01T00:00:00Z'
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            store = SQLiteRunStore(database)
            rows = store.get_publish_attempts("legacy-run")
            connection = sqlite3.connect(database)
            try:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(publish_attempts)").fetchall()
                }
            finally:
                connection.close()

        self.assertEqual(rows[0]["publish_id"], "legacy-publish")
        self.assertEqual(rows[0]["idempotency_key"], "legacy:legacy-publish")
        self.assertIn("remote_post_id", columns)
        self.assertIn("topic_tag", columns)

    def test_v03_publish_receipts_add_topic_tag_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "v03.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TABLE runs (
                        run_id TEXT PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        state TEXT NOT NULL,
                        error_code TEXT,
                        error_message TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE publish_attempts (
                        publish_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        draft_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        destination TEXT NOT NULL,
                        status TEXT NOT NULL,
                        remote_post_id TEXT,
                        http_status INTEGER,
                        attempt_count INTEGER NOT NULL DEFAULT 1,
                        reason TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            SQLiteRunStore(database)
            connection = sqlite3.connect(database)
            try:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(publish_attempts)").fetchall()
                }
            finally:
                connection.close()

        self.assertIn("topic_tag", columns)

    def test_v04_draft_revisions_add_markdown_import_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "v04.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TABLE runs (
                        run_id TEXT PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        state TEXT NOT NULL,
                        error_code TEXT,
                        error_message TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO runs(
                        run_id, account_id, topic, state, created_at, updated_at
                    ) VALUES(
                        'legacy-run', 'legacy-account', 'topic', 'completed',
                        '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
                    );
                    CREATE TABLE draft_revisions (
                        draft_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        parent_draft_id TEXT,
                        revision INTEGER NOT NULL,
                        origin TEXT NOT NULL CHECK (
                            origin IN ('initial_ai', 'ai_rewrite', 'human_edit')
                        ),
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(run_id, revision)
                    );
                    INSERT INTO draft_revisions(
                        draft_id, run_id, revision, origin, payload_json, created_at
                    ) VALUES(
                        'legacy-draft', 'legacy-run', 0, 'initial_ai', '{}',
                        '2026-01-01T00:00:00Z'
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            SQLiteRunStore(database)
            connection = sqlite3.connect(database)
            try:
                table_sql = connection.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'draft_revisions'"
                ).fetchone()[0]
                legacy = connection.execute(
                    "SELECT draft_id, origin FROM draft_revisions"
                ).fetchone()
            finally:
                connection.close()

        self.assertIn("markdown_import", table_sql)
        self.assertEqual(legacy, ("legacy-draft", "initial_ai"))


if __name__ == "__main__":
    unittest.main()
