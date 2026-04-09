from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


_UNSET = object()


def _coerce_jsonable(value: Any, limit: int = 4000) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > limit:
            return value[:limit] + "...<truncated>"
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _coerce_jsonable(val, limit=limit) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce_jsonable(item, limit=limit) for item in list(value)]
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(_coerce_jsonable(value), ensure_ascii=False)


def _json_loads(value: Any) -> Any:
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


class SQLiteTraceStore:
    _instances: dict[str, "SQLiteTraceStore"] = {}
    _instances_lock = threading.Lock()

    def __new__(cls, config: dict[str, Any] | None = None):
        config = config or {}
        db_path = cls._resolve_db_path(config)
        with cls._instances_lock:
            instance = cls._instances.get(db_path)
            if instance is None:
                instance = super().__new__(cls)
                cls._instances[db_path] = instance
        return instance

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        if getattr(self, "_initialized", False):
            return
        self.config = config or {}
        self.enabled = bool(self.config.get("trace_enabled", True))
        self.db_path = self._resolve_db_path(self.config)
        self._schema_lock = threading.Lock()
        self._ensure_schema()
        self._initialized = True

    @staticmethod
    def _resolve_db_path(config: dict[str, Any]) -> str:
        configured = config.get("trace_db_path")
        if configured:
            return str(Path(configured).expanduser().resolve())
        project_dir = Path(config.get("project_dir", ".")).resolve()
        return str((project_dir.parent / "debug" / "trace_viewer.sqlite3").resolve())

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _ensure_schema(self) -> None:
        if not self.enabled:
            return
        with self._schema_lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS trace_runs (
                        run_id TEXT PRIMARY KEY,
                        agent_name TEXT NOT NULL,
                        agent_type TEXT NOT NULL,
                        parent_run_id TEXT,
                        parent_node_name TEXT,
                        status TEXT NOT NULL,
                        started_at REAL NOT NULL,
                        finished_at REAL,
                        duration_ms INTEGER,
                        input_summary_json TEXT,
                        output_summary_json TEXT,
                        error_json TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS trace_nodes (
                        run_id TEXT NOT NULL,
                        node_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        started_at REAL,
                        finished_at REAL,
                        duration_ms INTEGER,
                        input_summary_json TEXT,
                        output_summary_json TEXT,
                        error_json TEXT,
                        latest_event_id INTEGER,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (run_id, node_name)
                    );

                    CREATE TABLE IF NOT EXISTS trace_steps (
                        step_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        agent_name TEXT NOT NULL,
                        agent_type TEXT NOT NULL,
                        node_name TEXT,
                        step_name TEXT NOT NULL,
                        step_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        started_at REAL NOT NULL,
                        finished_at REAL,
                        duration_ms INTEGER,
                        input_json TEXT,
                        output_json TEXT,
                        metrics_json TEXT,
                        error_json TEXT,
                        updated_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS trace_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        node_name TEXT,
                        step_id TEXT,
                        agent_name TEXT NOT NULL,
                        agent_type TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT,
                        created_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS trace_artifacts (
                        artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        node_name TEXT,
                        step_id TEXT,
                        artifact_type TEXT NOT NULL,
                        relative_path TEXT,
                        absolute_path TEXT,
                        created_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS viewer_researches (
                        research_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        query_text TEXT,
                        ticker TEXT,
                        company_name TEXT,
                        analysis_date TEXT,
                        parse_result_json TEXT,
                        status TEXT NOT NULL,
                        active_run_id TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS viewer_research_messages (
                        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        research_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        run_id TEXT,
                        metadata_json TEXT,
                        created_at REAL NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_trace_runs_started_at ON trace_runs(started_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_trace_runs_parent ON trace_runs(parent_run_id, parent_node_name);
                    CREATE INDEX IF NOT EXISTS idx_trace_nodes_run_id ON trace_nodes(run_id);
                    CREATE INDEX IF NOT EXISTS idx_trace_steps_run_id ON trace_steps(run_id);
                    CREATE INDEX IF NOT EXISTS idx_trace_steps_node_name ON trace_steps(run_id, node_name);
                    CREATE INDEX IF NOT EXISTS idx_trace_events_run_id ON trace_events(run_id, event_id);
                    CREATE INDEX IF NOT EXISTS idx_trace_artifacts_run_id ON trace_artifacts(run_id, node_name);
                    CREATE INDEX IF NOT EXISTS idx_viewer_researches_updated_at ON viewer_researches(updated_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_viewer_research_messages_research_id ON viewer_research_messages(research_id, message_id ASC);
                    """
                )

    def _append_event(
        self,
        *,
        conn: sqlite3.Connection,
        run_id: str,
        agent_name: str,
        agent_type: str,
        event_type: str,
        node_name: str | None,
        step_id: str | None,
        payload: Any,
        created_at: float | None = None,
    ) -> int:
        created_at = created_at or time.time()
        cur = conn.execute(
            """
            INSERT INTO trace_events (
                run_id, node_name, step_id, agent_name, agent_type, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                node_name,
                step_id,
                agent_name,
                agent_type,
                event_type,
                _json_dumps(payload),
                created_at,
            ),
        )
        return int(cur.lastrowid)

    def _upsert_node(
        self,
        *,
        conn: sqlite3.Connection,
        run_id: str,
        node_name: str,
        status: str,
        started_at: float | None,
        finished_at: float | None,
        duration_ms: int | None,
        input_summary: Any = None,
        output_summary: Any = None,
        error: Any = None,
        latest_event_id: int | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO trace_nodes (
                run_id, node_name, status, started_at, finished_at, duration_ms,
                input_summary_json, output_summary_json, error_json, latest_event_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, node_name) DO UPDATE SET
                status=excluded.status,
                started_at=COALESCE(trace_nodes.started_at, excluded.started_at),
                finished_at=excluded.finished_at,
                duration_ms=excluded.duration_ms,
                input_summary_json=COALESCE(trace_nodes.input_summary_json, excluded.input_summary_json),
                output_summary_json=excluded.output_summary_json,
                error_json=excluded.error_json,
                latest_event_id=excluded.latest_event_id,
                updated_at=excluded.updated_at
            """,
            (
                run_id,
                node_name,
                status,
                started_at,
                finished_at,
                duration_ms,
                _json_dumps(input_summary),
                _json_dumps(output_summary),
                _json_dumps(error),
                latest_event_id,
                time.time(),
            ),
        )

    def run_started(
        self,
        *,
        run_id: str,
        agent_name: str,
        agent_type: str,
        started_at: float,
        input_summary: dict[str, Any] | None,
        parent_run_id: str | None,
        parent_node_name: str | None,
    ) -> None:
        if not self.enabled:
            return
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_runs (
                    run_id, agent_name, agent_type, parent_run_id, parent_node_name,
                    status, started_at, input_summary_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    agent_name=excluded.agent_name,
                    agent_type=excluded.agent_type,
                    parent_run_id=excluded.parent_run_id,
                    parent_node_name=excluded.parent_node_name,
                    status=excluded.status,
                    started_at=excluded.started_at,
                    input_summary_json=excluded.input_summary_json,
                    updated_at=excluded.updated_at
                """,
                (
                    run_id,
                    agent_name,
                    agent_type,
                    parent_run_id,
                    parent_node_name,
                    "running",
                    started_at,
                    _json_dumps(input_summary),
                    now,
                    now,
                ),
            )
            self._append_event(
                conn=conn,
                run_id=run_id,
                agent_name=agent_name,
                agent_type=agent_type,
                event_type="run_started",
                node_name=parent_node_name if agent_type != "graph" else None,
                step_id=None,
                payload={
                    "started_at": started_at,
                    "input_summary": input_summary,
                    "parent_run_id": parent_run_id,
                    "parent_node_name": parent_node_name,
                },
                created_at=started_at,
            )

    def run_finished(self, run_trace: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE trace_runs
                SET status=?, finished_at=?, duration_ms=?, output_summary_json=?, error_json=?, updated_at=?
                WHERE run_id=?
                """,
                (
                    run_trace.get("status"),
                    run_trace.get("finished_at"),
                    run_trace.get("duration_ms"),
                    _json_dumps(run_trace.get("output_summary")),
                    _json_dumps(run_trace.get("error")),
                    time.time(),
                    run_trace.get("run_id"),
                ),
            )
            self._append_event(
                conn=conn,
                run_id=run_trace["run_id"],
                agent_name=run_trace["agent_name"],
                agent_type=run_trace["agent_type"],
                event_type="run_finished",
                node_name=None,
                step_id=None,
                payload={
                    "status": run_trace.get("status"),
                    "finished_at": run_trace.get("finished_at"),
                    "duration_ms": run_trace.get("duration_ms"),
                    "output_summary": run_trace.get("output_summary"),
                    "error": run_trace.get("error"),
                },
                created_at=run_trace.get("finished_at"),
            )

    def step_started(
        self,
        *,
        run_id: str,
        agent_name: str,
        agent_type: str,
        step_id: str,
        step_name: str,
        step_type: str,
        node_name: str | None,
        started_at: float,
        input_payload: dict[str, Any] | None,
    ) -> None:
        if not self.enabled:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_steps (
                    step_id, run_id, agent_name, agent_type, node_name, step_name, step_type,
                    status, started_at, input_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(step_id) DO UPDATE SET
                    status=excluded.status,
                    input_json=excluded.input_json,
                    updated_at=excluded.updated_at
                """,
                (
                    step_id,
                    run_id,
                    agent_name,
                    agent_type,
                    node_name,
                    step_name,
                    step_type,
                    "running",
                    started_at,
                    _json_dumps(input_payload),
                    time.time(),
                ),
            )
            event_id = self._append_event(
                conn=conn,
                run_id=run_id,
                agent_name=agent_name,
                agent_type=agent_type,
                event_type="step_started",
                node_name=node_name,
                step_id=step_id,
                payload={
                    "step_name": step_name,
                    "step_type": step_type,
                    "started_at": started_at,
                    "input": input_payload,
                },
                created_at=started_at,
            )
            if agent_type == "graph" and step_type == "node" and node_name:
                self._upsert_node(
                    conn=conn,
                    run_id=run_id,
                    node_name=node_name,
                    status="running",
                    started_at=started_at,
                    finished_at=None,
                    duration_ms=None,
                    input_summary=input_payload,
                    latest_event_id=event_id,
                )

    def step_finished(self, *, run_id: str, agent_name: str, agent_type: str, step: dict[str, Any], node_name: str | None) -> None:
        if not self.enabled:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE trace_steps
                SET status=?, finished_at=?, duration_ms=?, output_json=?, metrics_json=?, updated_at=?
                WHERE step_id=?
                """,
                (
                    step.get("status"),
                    step.get("finished_at"),
                    step.get("duration_ms"),
                    _json_dumps(step.get("output")),
                    _json_dumps(step.get("metrics")),
                    time.time(),
                    step["step_id"],
                ),
            )
            event_id = self._append_event(
                conn=conn,
                run_id=run_id,
                agent_name=agent_name,
                agent_type=agent_type,
                event_type="step_finished",
                node_name=node_name,
                step_id=step["step_id"],
                payload={
                    "step_name": step.get("name"),
                    "step_type": step.get("step_type"),
                    "status": step.get("status"),
                    "finished_at": step.get("finished_at"),
                    "duration_ms": step.get("duration_ms"),
                    "output": step.get("output"),
                    "metrics": step.get("metrics"),
                },
                created_at=step.get("finished_at"),
            )
            if agent_type == "graph" and step.get("step_type") == "node" and node_name:
                self._upsert_node(
                    conn=conn,
                    run_id=run_id,
                    node_name=node_name,
                    status="success",
                    started_at=step.get("started_at"),
                    finished_at=step.get("finished_at"),
                    duration_ms=step.get("duration_ms"),
                    input_summary=step.get("input"),
                    output_summary=step.get("output"),
                    latest_event_id=event_id,
                )

    def step_failed(self, *, run_id: str, agent_name: str, agent_type: str, step: dict[str, Any], node_name: str | None) -> None:
        if not self.enabled:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE trace_steps
                SET status=?, finished_at=?, duration_ms=?, error_json=?, updated_at=?
                WHERE step_id=?
                """,
                (
                    step.get("status"),
                    step.get("finished_at"),
                    step.get("duration_ms"),
                    _json_dumps(step.get("error")),
                    time.time(),
                    step["step_id"],
                ),
            )
            event_id = self._append_event(
                conn=conn,
                run_id=run_id,
                agent_name=agent_name,
                agent_type=agent_type,
                event_type="step_failed",
                node_name=node_name,
                step_id=step["step_id"],
                payload={
                    "step_name": step.get("name"),
                    "step_type": step.get("step_type"),
                    "status": step.get("status"),
                    "finished_at": step.get("finished_at"),
                    "duration_ms": step.get("duration_ms"),
                    "error": step.get("error"),
                },
                created_at=step.get("finished_at"),
            )
            if agent_type == "graph" and step.get("step_type") == "node" and node_name:
                self._upsert_node(
                    conn=conn,
                    run_id=run_id,
                    node_name=node_name,
                    status="failed",
                    started_at=step.get("started_at"),
                    finished_at=step.get("finished_at"),
                    duration_ms=step.get("duration_ms"),
                    input_summary=step.get("input"),
                    error=step.get("error"),
                    latest_event_id=event_id,
                )

    def record_artifact(
        self,
        *,
        run_id: str,
        node_name: str | None,
        step_id: str | None,
        artifact_type: str,
        ref: dict[str, Any],
    ) -> None:
        if not self.enabled:
            return
        created_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_artifacts (
                    run_id, node_name, step_id, artifact_type, relative_path, absolute_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    node_name,
                    step_id,
                    artifact_type,
                    ref.get("relative_path"),
                    ref.get("absolute_path"),
                    created_at,
                ),
            )
            self._append_event(
                conn=conn,
                run_id=run_id,
                agent_name="artifact_store",
                agent_type="artifact_store",
                event_type="artifact_written",
                node_name=node_name,
                step_id=step_id,
                payload={
                    "artifact_type": artifact_type,
                    "ref": ref,
                },
                created_at=created_at,
            )

    def list_runs(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        ticker: str | None = None,
        agent_type: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM trace_runs WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if ticker:
            query += " AND json_extract(input_summary_json, '$.ticker') = ?"
            params.append(ticker)
        if agent_type:
            query += " AND agent_type = ?"
            params.append(agent_type)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_run(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trace_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def list_nodes(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trace_nodes WHERE run_id = ? ORDER BY started_at ASC, node_name ASC",
                (run_id,),
            ).fetchall()
        return [self._row_to_node(row) for row in rows]

    def get_node(self, run_id: str, node_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trace_nodes WHERE run_id = ? AND node_name = ?",
                (run_id, node_name),
            ).fetchone()
        return self._row_to_node(row) if row else None

    def list_steps(self, run_id: str, *, node_name: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if node_name:
                rows = conn.execute(
                    "SELECT * FROM trace_steps WHERE run_id = ? AND node_name = ? ORDER BY started_at ASC",
                    (run_id, node_name),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trace_steps WHERE run_id = ? ORDER BY started_at ASC",
                    (run_id,),
                ).fetchall()
        return [self._row_to_step(row) for row in rows]

    def list_events(self, run_id: str, *, after_event_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trace_events
                WHERE run_id = ? AND event_id > ?
                ORDER BY event_id ASC
                LIMIT ?
                """,
                (run_id, after_event_id, limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_child_runs(self, parent_run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trace_runs WHERE parent_run_id = ? ORDER BY started_at ASC",
                (parent_run_id,),
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def list_artifacts(self, run_id: str, *, node_name: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if node_name:
                rows = conn.execute(
                    "SELECT * FROM trace_artifacts WHERE run_id = ? AND node_name = ? ORDER BY artifact_id ASC",
                    (run_id, node_name),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trace_artifacts WHERE run_id = ? ORDER BY artifact_id ASC",
                    (run_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trace_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        return dict(row) if row else None

    def create_research(
        self,
        *,
        research_id: str,
        title: str,
        query_text: str | None = None,
        ticker: str | None = None,
        company_name: str | None = None,
        analysis_date: str | None = None,
        parse_result: dict[str, Any] | None = None,
        status: str = "draft",
        active_run_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO viewer_researches (
                    research_id, title, query_text, ticker, company_name, analysis_date, parse_result_json,
                    status, active_run_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    research_id,
                    title,
                    query_text,
                    ticker,
                    company_name,
                    analysis_date,
                    _json_dumps(parse_result),
                    status,
                    active_run_id,
                    now,
                    now,
                ),
            )
        return self.get_research(research_id) or {}

    def list_researches(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM viewer_researches
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_research(row) for row in rows]

    def get_research(self, research_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM viewer_researches WHERE research_id = ?",
                (research_id,),
            ).fetchone()
        return self._row_to_research(row) if row else None

    def update_research(
        self,
        research_id: str,
        *,
        title: str | None | object = _UNSET,
        query_text: str | None | object = _UNSET,
        ticker: str | None | object = _UNSET,
        company_name: str | None | object = _UNSET,
        analysis_date: str | None | object = _UNSET,
        parse_result: dict[str, Any] | None | object = _UNSET,
        status: str | None | object = _UNSET,
        active_run_id: str | None | object = _UNSET,
    ) -> dict[str, Any] | None:
        updates: list[str] = []
        values: list[Any] = []
        if title is not _UNSET:
            updates.append("title = ?")
            values.append(title)
        if query_text is not _UNSET:
            updates.append("query_text = ?")
            values.append(query_text)
        if ticker is not _UNSET:
            updates.append("ticker = ?")
            values.append(ticker)
        if company_name is not _UNSET:
            updates.append("company_name = ?")
            values.append(company_name)
        if analysis_date is not _UNSET:
            updates.append("analysis_date = ?")
            values.append(analysis_date)
        if parse_result is not _UNSET:
            updates.append("parse_result_json = ?")
            values.append(_json_dumps(parse_result))
        if status is not _UNSET:
            updates.append("status = ?")
            values.append(status)
        if active_run_id is not _UNSET:
            updates.append("active_run_id = ?")
            values.append(active_run_id)
        if not updates:
            return self.get_research(research_id)
        updates.append("updated_at = ?")
        values.append(time.time())
        values.append(research_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE viewer_researches SET {', '.join(updates)} WHERE research_id = ?",
                values,
            )
        return self.get_research(research_id)

    def append_research_message(
        self,
        *,
        research_id: str,
        role: str,
        content: str,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO viewer_research_messages (
                    research_id, role, content, run_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    research_id,
                    role,
                    content,
                    run_id,
                    _json_dumps(metadata),
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE viewer_researches
                SET updated_at = ?, active_run_id = COALESCE(?, active_run_id)
                WHERE research_id = ?
                """,
                (now, run_id, research_id),
            )
            message_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM viewer_research_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        return self._row_to_research_message(row) if row else {}

    def list_research_messages(self, research_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM viewer_research_messages
                WHERE research_id = ?
                ORDER BY message_id ASC
                """,
                (research_id,),
            ).fetchall()
        return [self._row_to_research_message(row) for row in rows]

    def claim_research_ready_for_run(self, research_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE viewer_researches
                SET status = 'running', updated_at = ?
                WHERE research_id = ? AND status = 'ready'
                """,
                (now, research_id),
            )
            if cur.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT * FROM viewer_researches WHERE research_id = ?",
                (research_id,),
            ).fetchone()
        return self._row_to_research(row) if row else None

    def _row_to_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            **dict(row),
            "input_summary": _json_loads(row["input_summary_json"]),
            "output_summary": _json_loads(row["output_summary_json"]),
            "error": _json_loads(row["error_json"]),
        }

    def _row_to_node(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            **dict(row),
            "input_summary": _json_loads(row["input_summary_json"]),
            "output_summary": _json_loads(row["output_summary_json"]),
            "error": _json_loads(row["error_json"]),
        }

    def _row_to_step(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            **dict(row),
            "input": _json_loads(row["input_json"]),
            "output": _json_loads(row["output_json"]),
            "metrics": _json_loads(row["metrics_json"]),
            "error": _json_loads(row["error_json"]),
        }

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            **dict(row),
            "payload": _json_loads(row["payload_json"]),
        }

    def _row_to_research_message(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            **dict(row),
            "metadata": _json_loads(row["metadata_json"]),
        }

    def _row_to_research(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["parse_result"] = _json_loads(payload.get("parse_result_json"))
        payload.pop("parse_result_json", None)
        return payload
