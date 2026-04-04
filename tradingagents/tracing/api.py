from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from tradingagents.default_config import DEFAULT_CONFIG

from .sqlite_store import SQLiteTraceStore


def create_trace_viewer_app(config: dict[str, Any] | None = None) -> FastAPI:
    cfg = DEFAULT_CONFIG.copy()
    if config:
        cfg.update(config)
    store = SQLiteTraceStore(cfg)

    app = FastAPI(title="TradingAgents Trace Viewer API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "trace_db_path": store.db_path}

    @app.get("/api/runs")
    def list_runs(
        limit: int = Query(50, ge=1, le=500),
        status: str | None = None,
        ticker: str | None = None,
        agent_type: str | None = Query("graph"),
    ) -> dict[str, Any]:
        return {"runs": store.list_runs(limit=limit, status=status, ticker=ticker, agent_type=agent_type)}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        nodes = store.list_nodes(run_id)
        child_runs = store.list_child_runs(run_id)
        artifacts = store.list_artifacts(run_id)
        return {
            "run": run,
            "graph": {
                "nodes": nodes,
                "edges": [
                    ["company_context", "technical"],
                    ["company_context", "fundamental"],
                    ["company_context", "event_news"],
                    ["company_context", "sector_flow"],
                    ["technical", "collect_results"],
                    ["fundamental", "collect_results"],
                    ["event_news", "collect_results"],
                    ["sector_flow", "collect_results"],
                    ["collect_results", "strategy_style"],
                    ["strategy_style", "dispatch_post_strategy"],
                    ["dispatch_post_strategy", "strategy_decision"],
                    ["dispatch_post_strategy", "company_report"],
                    ["strategy_decision", "collect_postprocess"],
                    ["company_report", "collect_postprocess"],
                    ["collect_postprocess", "final_report"],
                ],
            },
            "child_runs": child_runs,
            "artifacts": artifacts,
        }

    @app.get("/api/runs/{run_id}/nodes/{node_name}")
    def get_node(run_id: str, node_name: str) -> dict[str, Any]:
        node = store.get_node(run_id, node_name)
        if not node:
            raise HTTPException(status_code=404, detail="node not found")
        steps = store.list_steps(run_id, node_name=node_name)
        artifacts = store.list_artifacts(run_id, node_name=node_name)
        child_runs = [run for run in store.list_child_runs(run_id) if run.get("parent_node_name") == node_name]
        return {
            "run_id": run_id,
            "node": node,
            "steps": steps,
            "artifacts": artifacts,
            "child_runs": child_runs,
        }

    @app.get("/api/runs/{run_id}/events")
    def get_events(
        run_id: str,
        after_event_id: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict[str, Any]:
        events = store.list_events(run_id, after_event_id=after_event_id, limit=limit)
        next_after = events[-1]["event_id"] if events else after_event_id
        return {"events": events, "next_after_event_id": next_after}

    @app.get("/api/runs/{run_id}/steps")
    def get_steps(
        run_id: str,
        node_name: str | None = None,
    ) -> dict[str, Any]:
        return {"steps": store.list_steps(run_id, node_name=node_name)}

    @app.get("/api/runs/{run_id}/stream")
    async def stream_events(
        run_id: str,
        after_event_id: int = Query(0, ge=0),
        poll_interval_ms: int = Query(1000, ge=200, le=5000),
    ) -> StreamingResponse:
        async def event_generator():
            current = after_event_id
            while True:
                events = store.list_events(run_id, after_event_id=current, limit=500)
                if events:
                    for event in events:
                        current = event["event_id"]
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    run = store.get_run(run_id)
                    if run and run.get("status") in {"success", "failed"}:
                        yield "event: completed\ndata: {}\n\n"
                        break
                await asyncio.sleep(poll_interval_ms / 1000.0)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/api/artifacts/{artifact_id}")
    def get_artifact(artifact_id: int):
        artifact = store.get_artifact(artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="artifact not found")
        path = artifact.get("absolute_path")
        if not path or not Path(path).exists():
            raise HTTPException(status_code=404, detail="artifact file not found")
        file_path = Path(path)
        if file_path.suffix.lower() == ".json":
            try:
                return JSONResponse(json.loads(file_path.read_text(encoding="utf-8")))
            except Exception:
                return FileResponse(str(file_path))
        return FileResponse(str(file_path))

    return app


app = create_trace_viewer_app()
