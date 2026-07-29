"""SQLite store shared by the CLI, AI handoff, and future review UI."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from ..ai.models import ContentRequest, CriticResult, DraftPost, ResearchBrief, TokenUsage
from ..critics import RuleCriticResult
from ..policy import AccountPolicy
from .contracts import EventState, RunEvent, RunState, RunStep

SCHEMA_VERSION = "0.5"

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

CREATE TABLE IF NOT EXISTS workflow_items (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
    current_draft_id TEXT NOT NULL,
    state TEXT NOT NULL,
    rewrite_count INTEGER NOT NULL DEFAULT 0 CHECK (rewrite_count BETWEEN 0 AND 2),
    version INTEGER NOT NULL DEFAULT 1,
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS draft_revisions (
    draft_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    parent_draft_id TEXT,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    origin TEXT NOT NULL CHECK (
        origin IN ('initial_ai', 'ai_rewrite', 'human_edit', 'markdown_import')
    ),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, revision)
);

CREATE TABLE IF NOT EXISTS critic_results (
    critic_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    draft_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    rule_passed INTEGER NOT NULL,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    decision TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    draft_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('approve', 'reject', 'edit')),
    actor TEXT NOT NULL,
    note TEXT,
    edited_content TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publish_attempts (
    publish_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    draft_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    destination TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'published', 'blocked', 'dry_run', 'failed')
    ),
    remote_post_id TEXT,
    topic_tag TEXT,
    http_status INTEGER,
    attempt_count INTEGER NOT NULL DEFAULT 1 CHECK (attempt_count >= 0),
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_cases (
    case_key TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    account_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    run_id TEXT,
    error_code TEXT,
    error_message TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_state ON workflow_items(state, updated_at);
CREATE INDEX IF NOT EXISTS idx_draft_revisions_run ON draft_revisions(run_id, revision);
CREATE INDEX IF NOT EXISTS idx_critic_results_run ON critic_results(run_id, revision);
CREATE INDEX IF NOT EXISTS idx_review_actions_run ON review_actions(run_id, action_id);
CREATE INDEX IF NOT EXISTS idx_publish_attempts_run ON publish_attempts(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_evaluation_id ON evaluation_cases(evaluation_id, status);
"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = NORMAL")
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
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SQLITE_SCHEMA)
            self._migrate_publish_attempts(connection)
            self._migrate_draft_origins(connection)
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION,),
            )

    @staticmethod
    def _migrate_publish_attempts(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(publish_attempts)").fetchall()
        }
        if "idempotency_key" in columns:
            if "topic_tag" not in columns:
                connection.execute("ALTER TABLE publish_attempts ADD COLUMN topic_tag TEXT")
            return
        connection.execute("ALTER TABLE publish_attempts RENAME TO publish_attempts_legacy")
        connection.executescript(
            """
            CREATE TABLE publish_attempts (
                publish_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                draft_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                destination TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pending', 'published', 'blocked', 'dry_run', 'failed')
                ),
                remote_post_id TEXT,
                topic_tag TEXT,
                http_status INTEGER,
                attempt_count INTEGER NOT NULL DEFAULT 1 CHECK (attempt_count >= 0),
                reason TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO publish_attempts(
                publish_id, run_id, draft_id, idempotency_key, destination, status,
                remote_post_id, topic_tag, reason, payload_json, created_at
            )
            SELECT
                publish_id, run_id, draft_id, 'legacy:' || publish_id, 'mock', status,
                NULL, NULL, reason, payload_json, created_at
            FROM publish_attempts_legacy;
            DROP TABLE publish_attempts_legacy;
            CREATE INDEX IF NOT EXISTS idx_publish_attempts_run
                ON publish_attempts(run_id, created_at);
            """
        )

    @staticmethod
    def _migrate_draft_origins(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'draft_revisions'"
        ).fetchone()
        schema_sql = str(row["sql"] or "") if row else ""
        if "markdown_import" in schema_sql:
            return
        connection.executescript(
            """
            ALTER TABLE draft_revisions RENAME TO draft_revisions_legacy;
            CREATE TABLE draft_revisions (
                draft_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                parent_draft_id TEXT,
                revision INTEGER NOT NULL CHECK (revision >= 0),
                origin TEXT NOT NULL CHECK (
                    origin IN ('initial_ai', 'ai_rewrite', 'human_edit', 'markdown_import')
                ),
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, revision)
            );
            INSERT INTO draft_revisions(
                draft_id, run_id, parent_draft_id, revision, origin, payload_json, created_at
            )
            SELECT
                draft_id, run_id, parent_draft_id, revision, origin, payload_json, created_at
            FROM draft_revisions_legacy;
            DROP TABLE draft_revisions_legacy;
            CREATE INDEX IF NOT EXISTS idx_draft_revisions_run
                ON draft_revisions(run_id, revision);
            """
        )

    def backup_bytes(self) -> bytes:
        """Return a consistent SQLite snapshot, including committed WAL data."""

        with tempfile.TemporaryDirectory(prefix="content-agent-backup-") as directory:
            backup_path = Path(directory) / "content_agent.sqlite3"
            source = sqlite3.connect(self.database_path, timeout=30)
            destination = sqlite3.connect(backup_path, timeout=30)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            return backup_path.read_bytes()

    def start_run(
        self,
        *,
        run_id: UUID,
        topic: str,
        policy: AccountPolicy,
        source_path: str | Path,
        request: ContentRequest | None = None,
    ) -> None:
        now = _utc_now().isoformat()
        policy_json = policy.model_dump_json()
        content_request = request or ContentRequest.from_inputs(topic=topic)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO runs(run_id, account_id, topic, state, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (str(run_id), policy.account_id, topic, RunState.RUNNING.value, now, now),
            )
            connection.execute(
                "INSERT INTO policies("
                "run_id, account_id, spec_version, source_path, payload_json, created_at"
                ") "
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
            connection.execute(
                "INSERT INTO artifacts(run_id, kind, entity_id, payload_json, created_at) "
                "VALUES(?, 'content_request', ?, ?, ?)",
                (
                    str(run_id),
                    str(content_request.request_id),
                    content_request.model_dump_json(),
                    now,
                ),
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
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (str(run_id),)).fetchone()
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

    def create_workflow(
        self,
        *,
        run_id: UUID,
        current_draft_id: UUID,
        state: str,
    ) -> None:
        now = _utc_now().isoformat()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO workflow_items(run_id, current_draft_id, state, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (str(run_id), str(current_draft_id), state, now, now),
            )

    def save_draft_revision(
        self,
        *,
        run_id: UUID | str,
        draft: DraftPost,
        revision: int,
        origin: str,
        parent_draft_id: UUID | str | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO draft_revisions(
                    draft_id, run_id, parent_draft_id, revision, origin, payload_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(draft.draft_id),
                    str(run_id),
                    str(parent_draft_id) if parent_draft_id else None,
                    revision,
                    origin,
                    draft.model_dump_json(),
                    _utc_now().isoformat(),
                ),
            )

    def save_critic_result(
        self,
        *,
        run_id: UUID | str,
        revision: int,
        rule_result: RuleCriticResult,
        critic: CriticResult,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO critic_results(
                    critic_id, run_id, draft_id, revision, rule_passed, score,
                    decision, rule_json, payload_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(critic.critic_id),
                    str(run_id),
                    str(critic.draft_id),
                    revision,
                    int(rule_result.passed),
                    critic.score,
                    critic.decision.value,
                    rule_result.model_dump_json(),
                    critic.model_dump_json(),
                    _utc_now().isoformat(),
                ),
            )

    def update_workflow(
        self,
        run_id: UUID | str,
        *,
        state: str,
        current_draft_id: UUID | str | None = None,
        rewrite_count: int | None = None,
        last_error_code: str | None = None,
        last_error_message: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        assignments = ["state = ?", "updated_at = ?", "version = version + 1"]
        values: list[Any] = [state, _utc_now().isoformat()]
        if current_draft_id is not None:
            assignments.append("current_draft_id = ?")
            values.append(str(current_draft_id))
        if rewrite_count is not None:
            assignments.append("rewrite_count = ?")
            values.append(rewrite_count)
        assignments.extend(["last_error_code = ?", "last_error_message = ?"])
        values.extend([last_error_code, last_error_message])
        values.append(str(run_id))
        where = "run_id = ?"
        if expected_version is not None:
            where += " AND version = ?"
            values.append(expected_version)

        with self._connection() as connection:
            cursor = connection.execute(
                f"UPDATE workflow_items SET {', '.join(assignments)} WHERE {where}",
                values,
            )
            if cursor.rowcount != 1:
                if expected_version is not None:
                    raise RuntimeError("Review item changed; refresh before applying this action.")
                raise KeyError(f"unknown workflow run_id: {run_id}")
            row = connection.execute(
                "SELECT * FROM workflow_items WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        return dict(row)

    def get_workflow(self, run_id: UUID | str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_items WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        return dict(row) if row else None

    def get_policy(self, run_id: UUID | str) -> AccountPolicy:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM policies WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        if not row:
            raise KeyError(f"policy not found for run_id: {run_id}")
        return AccountPolicy.model_validate_json(str(row["payload_json"]))

    def get_content_request(self, run_id: UUID | str) -> ContentRequest:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM artifacts WHERE run_id = ? AND kind = 'content_request'",
                (str(run_id),),
            ).fetchone()
        if not row:
            run = self.get_run(run_id)
            if not run:
                raise KeyError(f"content request not found for run_id: {run_id}")
            return ContentRequest.from_inputs(topic=str(run["topic"]))
        return ContentRequest.model_validate_json(str(row["payload_json"]))

    def get_research(self, run_id: UUID | str) -> ResearchBrief:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM artifacts WHERE run_id = ? AND kind = 'research_brief'",
                (str(run_id),),
            ).fetchone()
        if not row:
            raise KeyError(f"research brief not found for run_id: {run_id}")
        return ResearchBrief.model_validate_json(str(row["payload_json"]))

    def get_current_draft(self, run_id: UUID | str) -> DraftPost:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT d.payload_json
                FROM workflow_items w
                JOIN draft_revisions d ON d.draft_id = w.current_draft_id
                WHERE w.run_id = ?
                """,
                (str(run_id),),
            ).fetchone()
        if not row:
            raise KeyError(f"current draft not found for run_id: {run_id}")
        return DraftPost.model_validate_json(str(row["payload_json"]))

    def get_draft_revisions(self, run_id: UUID | str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT draft_id, parent_draft_id, revision, origin, payload_json, created_at
                FROM draft_revisions
                WHERE run_id = ?
                ORDER BY revision
                """,
                (str(run_id),),
            ).fetchall()
        return [
            {
                "draft_id": str(row["draft_id"]),
                "parent_draft_id": row["parent_draft_id"],
                "revision": int(row["revision"]),
                "origin": str(row["origin"]),
                "payload": json.loads(str(row["payload_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def get_latest_critic(self, run_id: UUID | str) -> CriticResult | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM critic_results WHERE run_id = ? ORDER BY revision DESC LIMIT 1",
                (str(run_id),),
            ).fetchone()
        return CriticResult.model_validate_json(str(row["payload_json"])) if row else None

    def get_critic_results(self, run_id: UUID | str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT critic_id, draft_id, revision, rule_passed, score, decision,
                       rule_json, payload_json, created_at
                FROM critic_results
                WHERE run_id = ?
                ORDER BY revision
                """,
                (str(run_id),),
            ).fetchall()
        return [
            {
                "critic_id": str(row["critic_id"]),
                "draft_id": str(row["draft_id"]),
                "revision": int(row["revision"]),
                "rule_passed": bool(row["rule_passed"]),
                "score": int(row["score"]),
                "decision": str(row["decision"]),
                "rule": json.loads(str(row["rule_json"])),
                "payload": json.loads(str(row["payload_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def next_revision_number(self, run_id: UUID | str) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(revision), -1) + 1 AS next_revision "
                "FROM draft_revisions WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        return int(row["next_revision"])

    def add_review_action(
        self,
        *,
        run_id: UUID | str,
        draft_id: UUID | str,
        action: str,
        actor: str,
        note: str | None = None,
        edited_content: str | None = None,
    ) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO review_actions(
                    run_id, draft_id, action, actor, note, edited_content, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_id),
                    str(draft_id),
                    action,
                    actor.strip(),
                    note.strip() if note else None,
                    edited_content,
                    _utc_now().isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def add_publish_attempt(self, *, receipt: BaseModel) -> None:
        payload = receipt.model_dump(mode="json")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO publish_attempts(
                    publish_id, run_id, draft_id, idempotency_key, destination, status,
                    remote_post_id, topic_tag, http_status, attempt_count, reason,
                    payload_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(payload["publish_id"]),
                    str(payload["run_id"]),
                    str(payload["draft_id"]),
                    str(payload["idempotency_key"]),
                    str(payload["destination"]),
                    str(payload["status"]),
                    payload.get("remote_post_id"),
                    payload.get("topic_tag"),
                    payload.get("http_status"),
                    int(payload.get("attempt_count", 1)),
                    str(payload["reason"]),
                    receipt.model_dump_json(),
                    _utc_now().isoformat(),
                ),
            )

    def update_publish_attempt(self, *, receipt: BaseModel) -> None:
        payload = receipt.model_dump(mode="json")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE publish_attempts
                SET status = ?, remote_post_id = ?, topic_tag = ?, http_status = ?,
                    attempt_count = ?, reason = ?, payload_json = ?
                WHERE publish_id = ? AND idempotency_key = ?
                """,
                (
                    str(payload["status"]),
                    payload.get("remote_post_id"),
                    payload.get("topic_tag"),
                    payload.get("http_status"),
                    int(payload.get("attempt_count", 1)),
                    str(payload["reason"]),
                    receipt.model_dump_json(),
                    str(payload["publish_id"]),
                    str(payload["idempotency_key"]),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"publish attempt not found: {payload['idempotency_key']}")

    def get_publish_attempt_by_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM publish_attempts WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return dict(row) if row else None

    def list_review_queue(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    w.run_id, r.account_id, r.topic, w.current_draft_id, w.state,
                    w.rewrite_count, w.version, w.last_error_code, w.last_error_message,
                    w.updated_at,
                    (SELECT score FROM critic_results c WHERE c.run_id = w.run_id
                     ORDER BY revision DESC LIMIT 1) AS score,
                    (SELECT decision FROM critic_results c WHERE c.run_id = w.run_id
                     ORDER BY revision DESC LIMIT 1) AS decision
                FROM workflow_items w
                JOIN runs r ON r.run_id = w.run_id
                WHERE w.state = 'human_review'
                ORDER BY w.updated_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_runs(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT r.*, w.state AS workflow_state, w.rewrite_count, w.current_draft_id,
                       (SELECT score FROM critic_results c WHERE c.run_id = r.run_id
                        ORDER BY revision DESC LIMIT 1) AS score
                FROM runs r
                LEFT JOIN workflow_items w ON w.run_id = r.run_id
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_review_actions(self, run_id: UUID | str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM review_actions WHERE run_id = ? ORDER BY action_id",
                (str(run_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_publish_attempts(self, run_id: UUID | str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM publish_attempts WHERE run_id = ? ORDER BY created_at",
                (str(run_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def score_history(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.run_id, r.account_id, c.revision, c.score, c.rule_passed,
                       c.decision, c.created_at
                FROM critic_results c
                JOIN runs r ON r.run_id = c.run_id
                ORDER BY c.created_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def usage_summary(self) -> dict[str, Any]:
        with self._connection() as connection:
            total = connection.execute(
                """
                SELECT COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       SUM(estimated_cost_usd) AS estimated_cost_usd,
                       SUM(CASE WHEN state = 'started' AND provider IS NOT NULL
                                THEN 1 ELSE 0 END) AS request_count,
                       SUM(CASE WHEN state = 'failed' AND retryable = 1
                                THEN 1 ELSE 0 END) AS retry_count
                FROM run_events
                """
            ).fetchone()
            by_provider = connection.execute(
                """
                SELECT provider, model, SUM(input_tokens) AS input_tokens,
                       SUM(output_tokens) AS output_tokens, SUM(total_tokens) AS total_tokens,
                       SUM(estimated_cost_usd) AS estimated_cost_usd,
                       SUM(CASE WHEN state = 'started' THEN 1 ELSE 0 END) AS request_count,
                       SUM(CASE WHEN state = 'failed' AND retryable = 1
                                THEN 1 ELSE 0 END) AS retry_count
                FROM run_events
                WHERE provider IS NOT NULL
                GROUP BY provider, model
                ORDER BY provider, model
                """
            ).fetchall()
            by_run = connection.execute(
                """
                SELECT r.run_id, r.account_id, r.topic,
                       SUM(e.input_tokens) AS input_tokens,
                       SUM(e.output_tokens) AS output_tokens,
                       SUM(e.total_tokens) AS total_tokens,
                       SUM(e.estimated_cost_usd) AS estimated_cost_usd,
                       SUM(CASE WHEN e.state = 'started' AND e.provider IS NOT NULL
                                THEN 1 ELSE 0 END) AS request_count,
                       SUM(CASE WHEN e.state = 'failed' AND e.retryable = 1
                                THEN 1 ELSE 0 END) AS retry_count
                FROM runs r
                JOIN run_events e ON e.run_id = r.run_id
                GROUP BY r.run_id, r.account_id, r.topic
                ORDER BY r.created_at DESC
                """
            ).fetchall()
        total_payload = dict(total)
        total_payload["retry_rate"] = self._retry_rate(total_payload)
        provider_payloads = [dict(row) for row in by_provider]
        run_payloads = [dict(row) for row in by_run]
        for payload in [*provider_payloads, *run_payloads]:
            payload["retry_rate"] = self._retry_rate(payload)
        return {
            "total": total_payload,
            "by_provider": provider_payloads,
            "by_run": run_payloads,
        }

    @staticmethod
    def _retry_rate(payload: dict[str, Any]) -> float:
        requests = int(payload.get("request_count") or 0)
        retries = int(payload.get("retry_count") or 0)
        return round(retries / requests, 4) if requests else 0.0

    def model_usage(
        self,
        *,
        provider: str,
        model: str,
        since: datetime,
    ) -> dict[str, int]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT SUM(CASE WHEN state = 'started' THEN 1 ELSE 0 END) AS request_count,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM run_events
                WHERE provider = ? AND model = ? AND created_at >= ?
                """,
                (provider, model, since.isoformat()),
            ).fetchone()
        return {
            "request_count": int(row["request_count"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
        }

    def upsert_evaluation_case(
        self,
        *,
        case_key: str,
        evaluation_id: str,
        topic: str,
        account_id: str,
        status: str,
        run_id: UUID | str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_cases(
                    case_key, evaluation_id, topic, account_id, status, run_id,
                    error_code, error_message, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_key) DO UPDATE SET
                    status = excluded.status,
                    run_id = excluded.run_id,
                    error_code = excluded.error_code,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    case_key,
                    evaluation_id,
                    topic,
                    account_id,
                    status,
                    str(run_id) if run_id else None,
                    error_code,
                    error_message,
                    _utc_now().isoformat(),
                ),
            )

    def list_evaluation_cases(self, evaluation_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM evaluation_cases WHERE evaluation_id = ? ORDER BY account_id, topic",
                (evaluation_id,),
            ).fetchall()
        return [dict(row) for row in rows]
