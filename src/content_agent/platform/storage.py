"""SQLite store shared by the CLI, AI handoff, and future review UI."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from pydantic import BaseModel

from ..ai.models import TokenUsage
from ..policy import AccountPolicy
from .contracts import EventState, RunEvent, RunState, RunStep

SCHEMA_VERSION = "0.1"

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('running', 'completed', 'failed')),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    source_path TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, kind)
);

CREATE TABLE IF NOT EXISTS run_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    step TEXT NOT NULL,
    state TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    provider TEXT,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL,
    error_code TEXT,
    error_message TEXT,
    retryable INTEGER NOT NULL DEFAULT 0,
    status_code INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id, event_id);
CREATE INDEX IF NOT EXISTS idx_runs_account_state ON runs(account_id, state);
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SQLiteRunStore:
    """Small explicit persistence API; every write is transactionally committed."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(SQLITE_SCHEMA)
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION,),
            )

    def start_run(
        self,
        *,
        run_id: UUID,
        topic: str,
        policy: AccountPolicy,
        source_path: str | Path,
    ) -> None:
        now = _utc_now().isoformat()
        policy_json = policy.model_dump_json()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO runs(run_id, account_id, topic, state, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (str(run_id), policy.account_id, topic, RunState.RUNNING.value, now, now),
            )
            connection.execute(
                "INSERT INTO policies(run_id, account_id, spec_version, source_path, payload_json, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    str(run_id),
                    policy.account_id,
                    policy.spec_version,
                    str(source_path),
                    policy_json,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO artifacts(run_id, kind, entity_id, payload_json, created_at) "
                "VALUES(?, 'account_policy', ?, ?, ?)",
                (str(run_id), policy.account_id, policy_json, now),
            )

    def save_artifact(
        self,
        *,
        run_id: UUID,
        kind: str,
        entity_id: UUID | str,
        artifact: BaseModel,
    ) -> None:
        now = _utc_now().isoformat()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO artifacts(run_id, kind, entity_id, payload_json, created_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (str(run_id), kind, str(entity_id), artifact.model_dump_json(), now),
            )

    def record_event(
        self,
        *,
        run_id: UUID,
        step: RunStep,
        state: EventState,
        attempt: int = 1,
        provider: str | None = None,
        model: str | None = None,
        usage: TokenUsage | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> RunEvent:
        event = RunEvent(
            run_id=run_id,
            step=step,
            state=state,
            attempt=attempt,
            provider=provider,
            model=model,
            usage=usage or TokenUsage(),
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            status_code=status_code,
        )
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO run_events(
                    run_id, step, state, attempt, provider, model,
                    input_tokens, output_tokens, total_tokens, estimated_cost_usd,
                    error_code, error_message, retryable, status_code, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_id),
                    step.value,
                    state.value,
                    attempt,
                    provider,
                    model,
                    event.usage.input_tokens,
                    event.usage.output_tokens,
                    event.usage.total_tokens,
                    event.usage.estimated_cost_usd,
                    error_code,
                    error_message,
                    int(retryable),
                    status_code,
                    event.created_at.isoformat(),
                ),
            )
            event.event_id = int(cursor.lastrowid)
        return event

    def complete_run(self, run_id: UUID) -> None:
        self._set_run_state(run_id, RunState.COMPLETED)

    def fail_run(self, run_id: UUID, *, error_code: str, error_message: str) -> None:
        self._set_run_state(
            run_id,
            RunState.FAILED,
            error_code=error_code,
            error_message=error_message,
        )

    def _set_run_state(
        self,
        run_id: UUID,
        state: RunState,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE runs SET state = ?, error_code = ?, error_message = ?, updated_at = ? "
                "WHERE run_id = ?",
                (state.value, error_code, error_message, _utc_now().isoformat(), str(run_id)),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown run_id: {run_id}")

    def get_run(self, run_id: UUID | str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        return dict(row) if row else None

    def get_events(self, run_id: UUID | str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? ORDER BY event_id",
                (str(run_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_artifacts(self, run_id: UUID | str) -> dict[str, dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT kind, entity_id, payload_json FROM artifacts WHERE run_id = ? ORDER BY artifact_id",
                (str(run_id),),
            ).fetchall()
        return {
            str(row["kind"]): {
                "entity_id": str(row["entity_id"]),
                "payload": json.loads(str(row["payload_json"])),
            }
            for row in rows
        }
