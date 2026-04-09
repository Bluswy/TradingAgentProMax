from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .schema import AgentTraceRun, TraceArtifactManifest, TraceArtifactRef
from .sqlite_store import SQLiteTraceStore


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


class TraceArtifactStore:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("trace_enabled", True))
        self.sqlite = SQLiteTraceStore(self.config)
        configured_dir = self.config.get("trace_artifact_dir")
        if configured_dir:
            self.base_dir = Path(configured_dir).expanduser().resolve()
        else:
            project_dir = Path(self.config.get("project_dir", ".")).resolve()
            self.base_dir = (project_dir.parent / "debug" / "traces").resolve()

    def _write_json(self, run_dir: Path, relative_path: str, payload: Any) -> TraceArtifactRef:
        target = run_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(_coerce_jsonable(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "relative_path": relative_path,
            "absolute_path": str(target),
        }

    def _record_artifact(
        self,
        *,
        run_id: str,
        node_name: str | None,
        step_id: str | None,
        artifact_type: str,
        ref: TraceArtifactRef,
    ) -> None:
        self.sqlite.record_artifact(
            run_id=run_id,
            node_name=node_name,
            step_id=step_id,
            artifact_type=artifact_type,
            ref=ref,
        )

    def rewrite_ref(self, ref: TraceArtifactRef, payload: Any) -> None:
        target = Path(ref["absolute_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(_coerce_jsonable(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def persist_run(self, run_trace: AgentTraceRun, state: dict[str, Any]) -> TraceArtifactManifest | None:
        if not self.enabled:
            return None

        run_id = str(run_trace["run_id"])
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        node_results_map = {
            "company_context": state.get("company_context"),
            "technical": state.get("technical_result"),
            "fundamental": state.get("fundamental_result"),
            "event_news": state.get("event_news_result"),
            "sector_flow": state.get("sector_flow_result"),
            "strategy_style": state.get("strategy_style_result"),
            "strategy_decision": state.get("strategy_decision_result"),
            "company_report": state.get("company_report_result"),
            "final_report": state.get("final_report_result"),
            "investment_debate": state.get("investment_debate_result"),
        }

        manifest: TraceArtifactManifest = {
            "run_id": run_id,
            "root_dir": str(run_dir),
            "nodes": {},
        }

        for step in run_trace.get("steps", []):
            node_name = str(step.get("name"))
            node_bucket = manifest["nodes"].setdefault(node_name, {})
            raw_debug = step.get("artifacts", {}).pop("raw_debug", None)
            if raw_debug is not None:
                node_bucket["node_trace"] = self._write_json(
                    run_dir,
                    f"nodes/{node_name}/node_trace.json",
                    raw_debug,
                )
                self._record_artifact(
                    run_id=run_id,
                    node_name=node_name,
                    step_id=step.get("step_id"),
                    artifact_type="node_trace",
                    ref=node_bucket["node_trace"],
                )
            node_result = node_results_map.get(node_name)
            if node_result is not None:
                node_bucket["result"] = self._write_json(
                    run_dir,
                    f"nodes/{node_name}/result.json",
                    node_result,
                )
                self._record_artifact(
                    run_id=run_id,
                    node_name=node_name,
                    step_id=step.get("step_id"),
                    artifact_type="result",
                    ref=node_bucket["result"],
                )
            if step.get("artifacts"):
                node_bucket["step_artifacts"] = self._write_json(
                    run_dir,
                    f"nodes/{node_name}/step_artifacts.json",
                    step["artifacts"],
                )
                self._record_artifact(
                    run_id=run_id,
                    node_name=node_name,
                    step_id=step.get("step_id"),
                    artifact_type="step_artifacts",
                    ref=node_bucket["step_artifacts"],
                )

        manifest["run_trace"] = self._write_json(run_dir, "run_trace.json", run_trace)
        self._record_artifact(
            run_id=run_id,
            node_name=None,
            step_id=None,
            artifact_type="run_trace",
            ref=manifest["run_trace"],
        )
        manifest["summary"] = self._write_json(
            run_dir,
            "summary.json",
            {
                "ticker": state.get("ticker"),
                "analysis_date": state.get("analysis_date"),
                "failure": state.get("failure"),
                "trace_steps": len(run_trace.get("steps", [])),
                "available_results": {
                    "company_context": state.get("company_context") is not None,
                    "technical": state.get("technical_result") is not None,
                    "fundamental": state.get("fundamental_result") is not None,
                    "event_news": state.get("event_news_result") is not None,
                    "sector_flow": state.get("sector_flow_result") is not None,
                    "strategy_style": state.get("strategy_style_result") is not None,
                    "strategy_decision": state.get("strategy_decision_result") is not None,
                    "company_report": state.get("company_report_result") is not None,
                    "final_report": state.get("final_report_result") is not None,
                },
                "ui_summary_schema_version": ((state.get("ui_summaries") or {}).get("technical") or {}).get("schema_version"),
                "ui_summary_keys": sorted((state.get("ui_summaries") or {}).keys()),
            },
        )
        self._record_artifact(
            run_id=run_id,
            node_name=None,
            step_id=None,
            artifact_type="summary",
            ref=manifest["summary"],
        )
        manifest["final_state"] = self._write_json(
            run_dir,
            "final_state.json",
            {
                "ticker": state.get("ticker"),
                "analysis_date": state.get("analysis_date"),
                "failure": state.get("failure"),
                "company_context": state.get("company_context"),
                "technical_result": state.get("technical_result"),
                "fundamental_result": state.get("fundamental_result"),
                "event_news_result": state.get("event_news_result"),
                "sector_flow_result": state.get("sector_flow_result"),
                "strategy_style_result": state.get("strategy_style_result"),
                "strategy_decision_result": state.get("strategy_decision_result"),
                "company_report_result": state.get("company_report_result"),
                "final_report_result": state.get("final_report_result"),
                "ui_summaries": state.get("ui_summaries"),
            },
        )
        self._record_artifact(
            run_id=run_id,
            node_name=None,
            step_id=None,
            artifact_type="final_state",
            ref=manifest["final_state"],
        )
        manifest_ref = self._write_json(run_dir, "manifest.json", manifest)
        self._record_artifact(
            run_id=run_id,
            node_name=None,
            step_id=None,
            artifact_type="manifest",
            ref=manifest_ref,
        )
        return manifest
