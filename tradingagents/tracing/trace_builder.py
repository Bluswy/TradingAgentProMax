from __future__ import annotations

import json
import os
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context import get_trace_parent
from .schema import AgentTraceRun, AgentTraceStep
from .sqlite_store import SQLiteTraceStore


def _now_ts() -> float:
    import time

    return time.time()


def _coerce_jsonable(value: Any, limit: int = 2000) -> Any:
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
        return {str(k): _coerce_jsonable(v, limit=limit) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce_jsonable(v, limit=limit) for v in list(value)]
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _safe_attrs(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    normalized = _coerce_jsonable(payload)
    result: dict[str, Any] = {}
    if isinstance(normalized, dict):
        for key, value in normalized.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                result[key] = value
            else:
                result[key] = json.dumps(value, ensure_ascii=False)[:4000]
    return result


class _NoopRun:
    metadata: dict[str, Any]

    def __init__(self) -> None:
        self.metadata = {}

    def end(self, outputs: dict[str, Any] | None = None) -> None:
        return None


class _NoopContext:
    def __enter__(self):
        return _NoopRun()

    def __exit__(self, exc_type, exc, tb):
        return False


class _LangSmithAdapter:
    def __init__(self, config: dict[str, Any], agent_name: str, run_id: str) -> None:
        self.enabled = bool(config.get("trace_enabled", True)) and bool(
            config.get("langsmith_enabled")
            or os.getenv("LANGSMITH_API_KEY")
            or os.getenv("LANGCHAIN_API_KEY")
        )
        self.project_name = config.get("langsmith_project_name") or config.get("trace_project_name") or "TradingAgents"
        self.agent_name = agent_name
        self.run_id = run_id
        self._root_ctx = None
        self._root_run = None

        if not self.enabled:
            self.trace = None
            self.tracing_context = None
            return

        if config.get("langsmith_api_key"):
            os.environ["LANGSMITH_API_KEY"] = str(config["langsmith_api_key"])
        if config.get("langsmith_endpoint"):
            os.environ["LANGSMITH_ENDPOINT"] = str(config["langsmith_endpoint"])

        try:
            from langsmith import trace, tracing_context
        except Exception:
            self.enabled = False
            self.trace = None
            self.tracing_context = None
            return

        self.trace = trace
        self.tracing_context = tracing_context

    def start_run(self, inputs: dict[str, Any]) -> None:
        if not self.enabled or self.trace is None or self.tracing_context is None:
            return
        self._tracing_ctx = self.tracing_context(
            enabled=True,
            project_name=self.project_name,
            tags=["tradingagents", self.agent_name],
            metadata={"agent_name": self.agent_name, "run_id": self.run_id},
        )
        self._tracing_ctx.__enter__()
        self._root_ctx = self.trace(
            self.agent_name,
            run_type="chain",
            inputs=_coerce_jsonable(inputs),
            project_name=self.project_name,
            tags=["tradingagents", self.agent_name],
            metadata={"agent_name": self.agent_name, "run_id": self.run_id},
            run_id=self.run_id,
        )
        self._root_run = self._root_ctx.__enter__()

    def end_run(self, outputs: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        if not self.enabled or self._root_ctx is None or self._root_run is None:
            return
        if error is None:
            self._root_run.end(outputs=_coerce_jsonable(outputs or {}))
            self._root_ctx.__exit__(None, None, None)
        else:
            self._root_ctx.__exit__(type(error), error, error.__traceback__)
        self._tracing_ctx.__exit__(None, None, None)

    def start_step(self, *, name: str, run_type: str, inputs: dict[str, Any]) -> tuple[Any, Any]:
        if not self.enabled or self.trace is None or self._root_run is None:
            return _NoopContext(), _NoopRun()
        ctx = self.trace(
            name,
            run_type=run_type,
            inputs=_coerce_jsonable(inputs),
            parent=self._root_run,
            project_name=self.project_name,
            tags=["tradingagents", self.agent_name, run_type],
            metadata={"agent_name": self.agent_name, "run_id": self.run_id},
        )
        run = ctx.__enter__()
        return ctx, run


class _OpenTelemetryAdapter:
    def __init__(self, config: dict[str, Any], agent_name: str) -> None:
        self.enabled = bool(config.get("trace_enabled", True)) and bool(config.get("otel_enabled"))
        self.agent_name = agent_name
        self._root_span = None
        self._otel_trace = None
        self._otel_context = None
        self._span_stack: dict[str, Any] = {}

        if not self.enabled:
            return
        try:
            from opentelemetry import context as otel_context
            from opentelemetry import trace as otel_trace
        except Exception:
            self.enabled = False
            return

        self._otel_context = otel_context
        self._otel_trace = otel_trace
        self._tracer = otel_trace.get_tracer("tradingagents")

    def start_run(self, run_id: str, inputs: dict[str, Any]) -> None:
        if not self.enabled:
            return
        span = self._tracer.start_span(self.agent_name)
        span.set_attribute("agent.run_id", run_id)
        span.set_attribute("agent.name", self.agent_name)
        for key, value in _safe_attrs(inputs).items():
            span.set_attribute(f"agent.input.{key}", value)
        self._root_span = span

    def end_run(self, outputs: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        if not self.enabled or self._root_span is None:
            return
        if outputs:
            for key, value in _safe_attrs(outputs).items():
                self._root_span.set_attribute(f"agent.output.{key}", value)
        if error is not None:
            self._root_span.record_exception(error)
        self._root_span.end()

    def start_step(self, step_id: str, name: str, step_type: str, inputs: dict[str, Any]) -> None:
        if not self.enabled:
            return
        context = self._otel_trace.set_span_in_context(self._root_span) if self._root_span is not None else None
        span = self._tracer.start_span(f"{self.agent_name}.{name}", context=context)
        span.set_attribute("agent.step_id", step_id)
        span.set_attribute("agent.step_name", name)
        span.set_attribute("agent.step_type", step_type)
        for key, value in _safe_attrs(inputs).items():
            span.set_attribute(f"agent.step.input.{key}", value)
        self._span_stack[step_id] = span

    def end_step(self, step_id: str, outputs: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        if not self.enabled:
            return
        span = self._span_stack.pop(step_id, None)
        if span is None:
            return
        if outputs:
            for key, value in _safe_attrs(outputs).items():
                span.set_attribute(f"agent.step.output.{key}", value)
        if error is not None:
            span.record_exception(error)
        span.end()


@dataclass
class _StepRuntime:
    step: AgentTraceStep
    langsmith_ctx: Any
    langsmith_run: Any


class AgentTraceBuilder:
    def __init__(
        self,
        *,
        agent_name: str,
        config: dict[str, Any] | None = None,
        input_summary: dict[str, Any] | None = None,
        agent_type: str = "agent",
    ) -> None:
        self.config = config or {}
        self.agent_name = agent_name
        self.agent_type = agent_type
        self.run_id = str(uuid.uuid4())
        self.started_at = _now_ts()
        self.steps: list[AgentTraceStep] = []
        self._active_steps: dict[str, _StepRuntime] = {}
        self.status: str = "running"
        self.error: dict[str, Any] | None = None
        self.output_summary: dict[str, Any] = {}
        self.input_summary = _coerce_jsonable(input_summary or {})
        self.parent_context = get_trace_parent()
        self.parent_run_id: str | None = self.parent_context.get("parent_run_id")
        self.parent_node_name: str | None = self.parent_context.get("parent_node_name")
        self.langsmith = _LangSmithAdapter(self.config, self.agent_name, self.run_id)
        self.otel = _OpenTelemetryAdapter(self.config, self.agent_name)
        self.sqlite = SQLiteTraceStore(self.config)
        self.langsmith.start_run(self.input_summary)
        self.otel.start_run(self.run_id, self.input_summary)
        self.sqlite.run_started(
            run_id=self.run_id,
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            started_at=self.started_at,
            input_summary=self.input_summary,
            parent_run_id=self.parent_run_id,
            parent_node_name=self.parent_node_name,
        )

    def start_step(
        self,
        *,
        name: str,
        step_type: str,
        input_payload: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> str:
        step_id = str(uuid.uuid4())
        payload = _coerce_jsonable(input_payload or {})
        step: AgentTraceStep = {
            "step_id": step_id,
            "step_type": step_type,
            "name": name,
            "status": "running",
            "started_at": _now_ts(),
            "input": payload,
            "output": {},
            "metrics": {},
            "error": None,
            "artifacts": _coerce_jsonable(artifacts or {}),
        }
        ctx, run = self.langsmith.start_step(
            name=name,
            run_type="tool" if step_type in {"tool_call", "search", "rerank", "normalize", "signal_generation"} else "chain",
            inputs=payload,
        )
        self.otel.start_step(step_id, name, step_type, payload)
        self._active_steps[step_id] = _StepRuntime(step=step, langsmith_ctx=ctx, langsmith_run=run)
        node_name = name if self.agent_type == "graph" and step_type == "node" else self.parent_node_name
        self.sqlite.step_started(
            run_id=self.run_id,
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            step_id=step_id,
            step_name=name,
            step_type=step_type,
            node_name=node_name,
            started_at=step["started_at"],
            input_payload=payload,
        )
        return step_id

    def end_step(
        self,
        step_id: str,
        *,
        output_payload: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        status: str = "success",
    ) -> None:
        runtime = self._active_steps.pop(step_id)
        step = runtime.step
        step["status"] = status
        step["finished_at"] = _now_ts()
        step["duration_ms"] = int((step["finished_at"] - step["started_at"]) * 1000)
        step["output"] = _coerce_jsonable(output_payload or {})
        step["metrics"] = _coerce_jsonable(metrics or {})
        runtime.langsmith_run.end(outputs=_coerce_jsonable(step["output"]))
        runtime.langsmith_ctx.__exit__(None, None, None)
        self.otel.end_step(step_id, outputs=step["output"])
        node_name = step["name"] if self.agent_type == "graph" and step["step_type"] == "node" else self.parent_node_name
        self.sqlite.step_finished(
            run_id=self.run_id,
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            step=step,
            node_name=node_name,
        )
        self.steps.append(step)

    def fail_step(self, step_id: str, error: Exception) -> None:
        runtime = self._active_steps.pop(step_id)
        step = runtime.step
        step["status"] = "failed"
        step["finished_at"] = _now_ts()
        step["duration_ms"] = int((step["finished_at"] - step["started_at"]) * 1000)
        step["error"] = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc(),
        }
        runtime.langsmith_ctx.__exit__(type(error), error, error.__traceback__)
        self.otel.end_step(step_id, error=error)
        node_name = step["name"] if self.agent_type == "graph" and step["step_type"] == "node" else self.parent_node_name
        self.sqlite.step_failed(
            run_id=self.run_id,
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            step=step,
            node_name=node_name,
        )
        self.steps.append(step)

    def finish(self, *, output_summary: dict[str, Any] | None = None, error: Exception | None = None) -> AgentTraceRun:
        finished_at = _now_ts()
        self.output_summary = _coerce_jsonable(output_summary or {})
        if error is not None and self._active_steps:
            for step_id in list(self._active_steps.keys()):
                try:
                    self.fail_step(step_id, error)
                except Exception:
                    pass
        if error is None:
            self.status = "success"
        else:
            self.status = "failed"
            self.error = {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "traceback": traceback.format_exc(),
            }
        run: AgentTraceRun = {
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "duration_ms": int((finished_at - self.started_at) * 1000),
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "error": self.error,
            "steps": self.steps,
            "observability": {
                "langsmith_enabled": self.langsmith.enabled,
                "langsmith_project_name": self.langsmith.project_name if self.langsmith.enabled else None,
                "otel_enabled": self.otel.enabled,
            },
        }
        self.langsmith.end_run(outputs=run["output_summary"], error=error)
        self.otel.end_run(outputs=run["output_summary"], error=error)
        self.sqlite.run_finished(run)
        return run
