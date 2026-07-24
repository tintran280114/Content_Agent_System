"""Validated SQLite snapshot handoff for the review-only Cloud dashboard."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import uuid4

MAX_SNAPSHOT_BYTES = 50 * 1024 * 1024
REQUIRED_SNAPSHOT_TABLES = {"runs", "run_events", "policies", "artifacts"}


def install_sqlite_snapshot(data: bytes, target: str | Path) -> None:
    """Validate a bounded SQLite snapshot, then atomically install it."""

    if not data.startswith(b"SQLite format 3\x00") or len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot must be a valid SQLite file no larger than 50 MB.")
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.upload")
    temporary.write_bytes(data)
    try:
        connection = sqlite3.connect(f"file:{temporary.as_posix()}?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
        if integrity != "ok":
            raise ValueError("Snapshot failed SQLite integrity validation.")
        missing = sorted(REQUIRED_SNAPSHOT_TABLES - tables)
        if missing:
            raise ValueError("Snapshot is missing required tables: " + ", ".join(missing))
        for suffix in ("-wal", "-shm"):
            destination.with_name(destination.name + suffix).unlink(missing_ok=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
