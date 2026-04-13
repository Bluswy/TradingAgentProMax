from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.agents.trading_analysis.trading_analysis_agent import TradingAnalysisAgent

from .sqlite_store import SQLiteTraceStore
from .research_parser import parse_research_query


class CreateResearchRequest(BaseModel):
    title: str = "新的研究"
    query_text: str | None = None


class ParseResearchRequest(BaseModel):
    query_text: str
    analysis_date: str | None = None


class RunResearchRequest(BaseModel):
    confirm: bool = True


class ResearchChatRequest(BaseModel):
    message: str


def _default_analysis_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _load_json_file(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_truncated_text(value: Any) -> bool:
    return isinstance(value, str) and "...<truncated>" in value


def _read_report_markdown(payload: dict[str, Any] | None, result_key: str) -> str:
    if not isinstance(payload, dict):
        return ""
    if result_key == "final_report_result":
        return str((payload.get("report_markdown") or ""))
    if result_key == "company_report_result":
        analysis_result = payload.get("analysis_result")
        if isinstance(analysis_result, dict):
            return str((analysis_result.get("report_markdown") or ""))
    return ""


def _recover_report_payload(
    payload: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_map = {
        (str(artifact.get("artifact_type")), str(artifact.get("node_name") or "")): artifact for artifact in artifacts
    }
    report_status: dict[str, Any] = {
        "recovered": False,
        "truncated": False,
        "recovered_nodes": [],
        "missing_nodes": [],
    }

    report_targets = (
        ("final_report_result", "final_report"),
        ("company_report_result", "company_report"),
    )
    for result_key, node_name in report_targets:
        current_payload = payload.get(result_key)
        current_markdown = _read_report_markdown(current_payload if isinstance(current_payload, dict) else None, result_key)
        needs_recovery = not current_markdown or _is_truncated_text(current_markdown)
        if not needs_recovery:
            continue
        artifact = artifact_map.get(("result", node_name))
        node_payload = _load_json_file((artifact or {}).get("absolute_path"))
        recovered_markdown = _read_report_markdown(node_payload, result_key)
        if node_payload and recovered_markdown and not _is_truncated_text(recovered_markdown):
            payload[result_key] = node_payload
            report_status["recovered"] = True
            report_status["recovered_nodes"].append(node_name)
            continue
        report_status["missing_nodes"].append(node_name)

    final_report_markdown = _read_report_markdown(payload.get("final_report_result"), "final_report_result")
    company_report_markdown = _read_report_markdown(payload.get("company_report_result"), "company_report_result")
    report_status["truncated"] = _is_truncated_text(final_report_markdown) or _is_truncated_text(company_report_markdown)

    if report_status["recovered"] or report_status["truncated"]:
        payload["_report_artifact_status"] = report_status
    return payload


def _load_run_results(store: SQLiteTraceStore, run_id: str) -> dict[str, Any] | None:
    artifacts = store.list_artifacts(run_id)
    final_state = next((artifact for artifact in artifacts if artifact.get("artifact_type") == "final_state"), None)
    if final_state:
        payload = _load_json_file(final_state.get("absolute_path"))
        if payload:
            return _recover_report_payload(payload, artifacts)
    return None


def _build_chat_context(results: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": results.get("ticker"),
        "analysis_date": results.get("analysis_date"),
        "ui_summaries": results.get("ui_summaries"),
        "company_context": results.get("company_context"),
        "technical_result": results.get("technical_result"),
        "fundamental_result": results.get("fundamental_result"),
        "event_news_result": results.get("event_news_result"),
        "sector_flow_result": results.get("sector_flow_result"),
        "strategy_style_result": results.get("strategy_style_result"),
        "strategy_decision_result": results.get("strategy_decision_result"),
        "company_report_result": results.get("company_report_result"),
        "final_report_result": results.get("final_report_result"),
    }


def _build_context_chat_reply(
    *,
    config: dict[str, Any],
    question: str,
    context_payload: dict[str, Any],
) -> str:
    try:
        llm_kwargs: dict[str, Any] = {"project_dir": config.get("project_dir")}
        provider = config.get("llm_provider")
        if provider == "openai" and config.get("openai_reasoning_effort"):
            llm_kwargs["reasoning_effort"] = config.get("openai_reasoning_effort")
        if provider == "google" and config.get("google_thinking_level"):
            llm_kwargs["thinking_level"] = config.get("google_thinking_level")
        if provider in ("bailian", "dashscope") and config.get("bailian_api_key"):
            llm_kwargs["api_key"] = config.get("bailian_api_key")
            llm_kwargs["bailian_enable_thinking"] = config.get("bailian_enable_thinking")
            if config.get("bailian_thinking_budget") is not None:
                llm_kwargs["bailian_thinking_budget"] = config.get("bailian_thinking_budget")
        llm = create_llm_client(
            provider=provider,
            model=config.get("quick_think_llm", "qwen3.5-flash"),
            base_url=config.get("backend_url"),
            **llm_kwargs,
        ).get_llm()
        messages = [
            SystemMessage(
                content=(
                    "你是 TradingAgents 的股票研究助手。\n"
                    "你必须仅基于提供的结构化研究结果和报告上下文回答问题，不要编造不存在的事实。\n"
                    "如果上下文不足，请明确指出缺口。\n"
                    "回答风格要求：简洁、中文、直接引用当前研究结论中的事实和冲突点。"
                )
            ),
            HumanMessage(
                content=(
                    "以下是当前 run 的研究上下文 JSON：\n"
                    f"{json.dumps(context_payload, ensure_ascii=False)}\n\n"
                    f"用户问题：{question}\n\n"
                    "请基于这些上下文回答用户，并优先引用：主策略、当前动作、关键风险、关键催化、技术/基本面/资金面的冲突。"
                )
            ),
        ]
        response = llm.invoke(messages)
        return str(response.content).strip()
    except Exception:
        ui_summaries = context_payload.get("ui_summaries", {})
        strategy = ui_summaries.get("strategy_style", {})
        decision = ui_summaries.get("strategy_decision", {})
        event_result = ui_summaries.get("event_news", {})
        return (
            f"当前上下文下，主策略是 {strategy.get('primary_label') or '未识别'}，"
            f"当前动作是 {decision.get('primary_label') or '未生成'}。"
            f"主要风险包括：{', '.join(decision.get('risks', [])[:3]) or '暂无明确风险摘要'}。"
            f"事件面摘要：{event_result.get('summary_zh') or '暂无事件摘要'}。"
            f"你的问题是“{question}”，当前已使用最新 run 结果作为回答上下文。"
        )


def _launch_research_job_for_research(
    *,
    store: SQLiteTraceStore,
    cfg: dict[str, Any],
    research_id: str,
    title: str,
    ticker: str,
    analysis_date: str,
    query_text: str,
) -> str:
    ready = threading.Event()
    holder: dict[str, str] = {}

    def on_run_created(run_id: str) -> None:
        holder["run_id"] = run_id
        store.update_research(
            research_id,
            title=title,
            ticker=ticker,
            analysis_date=analysis_date,
            status="running",
            active_run_id=run_id,
        )
        store.append_research_message(
            research_id=research_id,
            role="assistant",
            content=f"已开始研究 {title}（{ticker}），当前正在执行完整分析流程。",
            run_id=run_id,
            metadata={"source": "viewer_research_status", "kind": "running"},
        )
        ready.set()

    def worker() -> None:
        try:
            agent = TradingAnalysisAgent(config=cfg.copy(), debug=True)
            result = agent.analyze(ticker, analysis_date, on_run_created=on_run_created)
            run_id = holder.get("run_id") or (((result.get("run_trace") or {}) if isinstance(result, dict) else {}) or {}).get("run_id")
            if run_id:
                if result.get("failure"):
                    store.update_research(
                        research_id,
                        status="failed",
                        active_run_id=run_id,
                    )
                    store.append_research_message(
                        research_id=research_id,
                        role="assistant",
                        content=f"研究执行失败：{result['failure'].get('message') or '请稍后重试。'}",
                        run_id=run_id,
                        metadata={"source": "viewer_research_status", "kind": "failed"},
                    )
                else:
                    store.update_research(
                        research_id,
                        status="completed",
                        active_run_id=run_id,
                    )
                    store.append_research_message(
                        research_id=research_id,
                        role="assistant",
                        content="研究已完成，可以继续围绕本次研究结果追问。",
                        run_id=run_id,
                        metadata={"source": "viewer_research_status", "kind": "completed"},
                    )
        except Exception as error:
            ready.set()
            holder["startup_error"] = str(error)
            store.update_research(research_id, status="failed")
            store.append_research_message(
                research_id=research_id,
                role="assistant",
                content=f"研究启动失败：{error}",
                run_id=holder.get("run_id"),
                metadata={"source": "viewer_research_status", "kind": "failed"},
            )

    threading.Thread(target=worker, name=f"research-{research_id}", daemon=True).start()
    if not ready.wait(timeout=10):
        raise HTTPException(status_code=504, detail="research start timeout")
    run_id = holder.get("run_id")
    if not run_id:
        startup_error = holder.get("startup_error")
        if startup_error:
            raise HTTPException(status_code=503, detail=f"research start failed: {startup_error}")
        raise HTTPException(status_code=500, detail="research run not created")
    return run_id


def create_trace_viewer_app(config: dict[str, Any] | None = None) -> FastAPI:
    cfg = DEFAULT_CONFIG.copy()
    if config:
        cfg.update(config)
    store = SQLiteTraceStore(cfg)

    app = FastAPI(title="TradingAgents Trace Viewer API", version="0.1.0")
    web_dir = Path(__file__).resolve().parent / "web"
    dist_dir = web_dir / "dist"
    if dist_dir.exists():
        app.mount("/static", StaticFiles(directory=str(dist_dir)), name="static")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "trace_db_path": store.db_path}

    @app.get("/")
    def index():
        index_path = dist_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=503, detail="viewer dist not found, please build frontend first")
        return FileResponse(str(index_path))

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
        results = _load_run_results(store, run_id) or {}
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
            "ui_summaries": results.get("ui_summaries", {}),
        }

    @app.get("/api/runs/{run_id}/results")
    def get_run_results(run_id: str) -> dict[str, Any]:
        payload = _load_run_results(store, run_id)
        if not payload:
            raise HTTPException(status_code=404, detail="run results not found")
        return payload

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

    @app.get("/api/researches")
    def list_researches(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        researches = store.list_researches(limit=limit)
        for item in researches:
            run_id = item.get("active_run_id")
            if run_id:
                run = store.get_run(str(run_id))
                item["run_status"] = run.get("status") if run else None
        return {"researches": researches}

    @app.post("/api/researches")
    def create_research(payload: CreateResearchRequest) -> dict[str, Any]:
        research = store.create_research(
            research_id=str(uuid.uuid4()),
            title=payload.title,
            query_text=payload.query_text,
            status="draft",
        )
        return {"research": research}

    @app.get("/api/researches/{research_id}")
    def get_research(research_id: str) -> dict[str, Any]:
        research = store.get_research(research_id)
        if not research:
            raise HTTPException(status_code=404, detail="research not found")
        run_id = research.get("active_run_id")
        if run_id:
            run = store.get_run(str(run_id))
            research["run_status"] = run.get("status") if run else None
        return {
            "research": research,
            "messages": store.list_research_messages(research_id),
        }

    @app.delete("/api/researches/{research_id}")
    def delete_research(research_id: str) -> dict[str, Any]:
        research = store.get_research(research_id)
        if not research:
            raise HTTPException(status_code=404, detail="research not found")

        active_run_id = research.get("active_run_id")
        if research.get("status") == "running" or research.get("run_status") == "running":
            raise HTTPException(status_code=409, detail="研究进行中，暂不支持删除")
        if active_run_id:
            run = store.get_run(str(active_run_id))
            if run and run.get("status") == "running":
                raise HTTPException(status_code=409, detail="研究进行中，暂不支持删除")

        deleted = store.delete_research(research_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="research not found")
        return {"deleted": True, "research_id": research_id}

    @app.post("/api/researches/{research_id}/parse")
    def parse_research(research_id: str, payload: ParseResearchRequest) -> dict[str, Any]:
        research = store.get_research(research_id)
        if not research:
            raise HTTPException(status_code=404, detail="research not found")
        status = str(research.get("status") or "draft")
        if status in {"running", "completed"}:
            raise HTTPException(status_code=409, detail="research can no longer be reparsed")

        active_run_id = research.get("active_run_id")
        if active_run_id and status not in {"failed", "draft", "ready"}:
            raise HTTPException(status_code=409, detail="research already has an active run")

        parsed = parse_research_query(cfg, payload.query_text, payload.analysis_date)
        title = parsed.get("company_name") or parsed.get("ticker") or payload.query_text.strip() or "新的研究"
        next_status = "ready" if not parsed.get("needs_confirmation") else "draft"
        updated = store.update_research(
            research_id,
            title=title,
            query_text=payload.query_text.strip(),
            ticker=parsed.get("ticker"),
            company_name=parsed.get("company_name"),
            analysis_date=parsed.get("analysis_date"),
            parse_result=parsed,
            status=next_status,
            active_run_id=None if status == "failed" else active_run_id,
        )
        return {"research": updated, "parse_result": parsed}

    @app.post("/api/researches/{research_id}/run")
    def run_research(research_id: str, payload: RunResearchRequest) -> dict[str, Any]:
        research = store.get_research(research_id)
        if not research:
            raise HTTPException(status_code=404, detail="research not found")
        if not payload.confirm:
            raise HTTPException(status_code=400, detail="research run not confirmed")

        status = str(research.get("status") or "draft")
        if status == "completed":
            raise HTTPException(status_code=409, detail="research already has a completed run")
        if status == "running":
            raise HTTPException(status_code=409, detail="research already has an active run")

        ticker = research.get("ticker")
        analysis_date = research.get("analysis_date") or _default_analysis_date()
        query_text = research.get("query_text") or research.get("title") or ticker
        if not ticker:
            raise HTTPException(status_code=409, detail="research ticker not resolved")

        claimed = store.claim_research_ready_for_run(research_id)
        if not claimed:
            latest = store.get_research(research_id) or research
            latest_status = str(latest.get("status") or "draft")
            if latest_status == "running":
                raise HTTPException(status_code=409, detail="research already has an active run")
            if latest_status == "completed":
                raise HTTPException(status_code=409, detail="research already has a completed run")
            raise HTTPException(status_code=409, detail="research is not ready to run")

        user_message = store.append_research_message(
            research_id=research_id,
            role="user",
            content=query_text,
            run_id=None,
            metadata={"source": "viewer_research_start", "analysis_date": analysis_date},
        )
        run_id = _launch_research_job_for_research(
            store=store,
            cfg=cfg,
            research_id=research_id,
            title=str(claimed.get("title") or claimed.get("company_name") or ticker),
            ticker=str(ticker),
            analysis_date=str(analysis_date),
            query_text=str(query_text),
        )
        refreshed = store.get_research(research_id) or claimed
        refreshed["run_status"] = "running"
        return {
            "research": refreshed,
            "messages": store.list_research_messages(research_id),
            "run_id": run_id,
        }

    @app.get("/api/researches/{research_id}/messages")
    def get_research_messages(research_id: str) -> dict[str, Any]:
        research = store.get_research(research_id)
        if not research:
            raise HTTPException(status_code=404, detail="research not found")
        return {"messages": store.list_research_messages(research_id)}

    @app.post("/api/researches/{research_id}/chat")
    def chat_research(research_id: str, payload: ResearchChatRequest) -> dict[str, Any]:
        research = store.get_research(research_id)
        if not research:
            raise HTTPException(status_code=404, detail="research not found")
        if research.get("status") != "completed":
            raise HTTPException(status_code=409, detail="research is not ready for follow-up chat")
        active_run_id = research.get("active_run_id")
        if not active_run_id:
            raise HTTPException(status_code=409, detail="research has no completed run context")

        run = store.get_run(str(active_run_id))
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        results = _load_run_results(store, str(active_run_id))
        if not results:
            raise HTTPException(status_code=409, detail="run results not ready")

        user_message = store.append_research_message(
            research_id=research_id,
            role="user",
            content=payload.message,
            run_id=str(active_run_id),
            metadata={"source": "viewer_chat"},
        )
        reply = _build_context_chat_reply(
            config=cfg,
            question=payload.message,
            context_payload=_build_chat_context(results),
        )
        assistant_message = store.append_research_message(
            research_id=research_id,
            role="assistant",
            content=reply,
            run_id=str(active_run_id),
            metadata={"source": "viewer_chat", "run_status": run.get("status")},
        )
        refreshed = store.get_research(research_id) or research
        refreshed["run_status"] = run.get("status")
        return {
            "research": refreshed,
            "messages": [user_message, assistant_message],
        }

    return app


app = create_trace_viewer_app()
