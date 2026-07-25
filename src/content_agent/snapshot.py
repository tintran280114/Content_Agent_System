"""Validated SQLite snapshot handoff for the guided Cloud studio."""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

MAX_SNAPSHOT_BYTES = 50 * 1024 * 1024
REQUIRED_SNAPSHOT_TABLES = {"runs", "run_events", "policies", "artifacts"}
DEFAULT_SNAPSHOT_LIMIT = 20


def unique_snapshot_name(*, prefix: str = "content-agent") -> str:
    """Return a collision-resistant, human-sortable SQLite filename."""

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    return f"{prefix}-{timestamp}-{secrets.token_hex(5)}.sqlite3"


def save_rotating_snapshot(
    data: bytes,
    directory: str | Path,
    *,
    limit: int = DEFAULT_SNAPSHOT_LIMIT,
    prefix: str = "content-agent",
) -> Path:
    """Atomically save one unique snapshot and retain at most ``limit`` copies."""

    if limit < 1 or limit > 100:
        raise ValueError("snapshot rotation limit must be between 1 and 100")
    if not data.startswith(b"SQLite format 3\x00") or len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot must be a valid SQLite file no larger than 50 MB.")
    snapshot_directory = Path(directory)
    snapshot_directory.mkdir(parents=True, exist_ok=True)
    resolved_directory = snapshot_directory.resolve()
    destination = resolved_directory / unique_snapshot_name(prefix=prefix)
    temporary = resolved_directory / f".{destination.name}.{uuid4().hex}.tmp"
    temporary.write_bytes(data)
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    candidates = sorted(
        (
            path
            for path in resolved_directory.glob(f"{prefix}-*.sqlite3")
            if path.is_file() and path.resolve().parent == resolved_directory
        ),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    for expired in candidates[limit:]:
        expired.unlink(missing_ok=True)
    return destination


def install_sqlite_snapshot(
    data: bytes,
    target: str | Path,
    *,
    require_runs: bool = False,
) -> dict[str, int]:
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
                row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            run_count = (
                int(connection.execute("SELECT COUNT(1) FROM runs").fetchone()[0]) if "runs" in tables else 0
            )
            review_count = (
                int(
                    connection.execute(
                        "SELECT COUNT(1) FROM workflow_items WHERE state = 'human_review'"
                    ).fetchone()[0]
                )
                if "workflow_items" in tables
                else 0
            )
        finally:
            connection.close()
        if integrity != "ok":
            raise ValueError("Snapshot failed SQLite integrity validation.")
        missing = sorted(REQUIRED_SNAPSHOT_TABLES - tables)
        if missing:
            raise ValueError("Snapshot is missing required tables: " + ", ".join(missing))
        if require_runs and run_count == 0:
            raise ValueError(
                "This SQLite snapshot contains 0 runs, so there is nothing to display or approve. "
                "Run the content batch first, then upload the generated snapshot."
            )
        for suffix in ("-wal", "-shm"):
            destination.with_name(destination.name + suffix).unlink(missing_ok=True)
        os.replace(temporary, destination)
        return {"runs": run_count, "human_review": review_count}
    finally:
        temporary.unlink(missing_ok=True)
