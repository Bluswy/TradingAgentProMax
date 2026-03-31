from __future__ import annotations

import operator
import time
import traceback
from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import Annotated, TypedDict

from tradingagents.agents import (
    EventNewsAgent,
    FundamentalAgent,
    SectorFlowAgent,
    StrategyStyleAgent,
    TechnicalAgent,
)
from tradingagents.dataflows.company_context_service import build_company_context
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.tracing import AgentTraceBuilder, TraceArtifactStore


class StructuredAnalysisState(TypedDict, total=False):
    ticker: str
    analysis_date: str
    trace: Annotated[list[dict[str, Any]], operator.add]
    failures: Annotated[list[dict[str, Any]], operator.add]
    failure: dict[str, Any] | None
    company_context: dict[str, Any] | None
    technical_result: dict[str, Any] | None
    fundamental_result: dict[str, Any] | None
    event_news_result: dict[str, Any] | None
    sector_flow_result: dict[str, Any] | None
    strategy_style_result: dict[str, Any] | None
    run_trace: dict[str, Any] | None
    trace_artifacts: dict[str, Any] | None


def _now_ts() -> float:
    return time.time()


def _snapshot_for_trace(value: Any, limit: int = 1200) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _snapshot_for_trace(val, limit=limit) for key, val in value.items()}
    if isinstance(value, list):
        return [_snapshot_for_trace(item, limit=limit) for item in value[:20]]
    text = str(value)
    if len(text) <= limit:
        return value
    return text[:limit] + "...<truncated>"


def _append_trace(entry: dict[str, Any]) -> dict[str, Any]:
    return {"trace": [entry]}


def _append_failure(node_name: str, message: str) -> dict[str, Any]:
    return {"failures": [{"node": node_name, "message": message}]}


def _node_input_summary(state: dict[str, Any], node_name: str) -> dict[str, Any]:
    summary = {
        "ticker": state.get("ticker"),
        "analysis_date": state.get("analysis_date"),
        "has_company_context": state.get("company_context") is not None,
    }
    if node_name in {"technical", "fundamental", "event_news", "sector_flow"}:
        summary["company_context_keys"] = sorted((state.get("company_context") or {}).keys())
    elif node_name == "strategy_style":
        summary["has_technical"] = state.get("technical_result") is not None
        summary["has_fundamental"] = state.get("fundamental_result") is not None
        summary["has_event_news"] = state.get("event_news_result") is not None
        summary["has_sector_flow"] = state.get("sector_flow_result") is not None
    return summary


def _trace_success(
    node_name: str,
    started_at: float,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
    raw_debug: Any = None,
) -> dict[str, Any]:
    finished_at = _now_ts()
    return {
        "node": node_name,
        "status": "success",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(finished_at - started_at, 3),
        "input_summary": input_summary,
        "output_summary": output_summary,
        "raw_debug": raw_debug,
    }


def _trace_error(node_name: str, started_at: float, input_summary: dict[str, Any], error: Exception) -> dict[str, Any]:
    finished_at = _now_ts()
    return {
        "node": node_name,
        "status": "error",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(finished_at - started_at, 3),
        "input_summary": input_summary,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "traceback": traceback.format_exc(),
    }


def _build_output_summary(node_name: str, result: dict[str, Any]) -> dict[str, Any]:
    analysis_result = result.get("analysis_result") or {}
    if node_name == "technical":
        return {
            "effective_trade_date": analysis_result.get("effective_trade_date"),
            "trend": analysis_result.get("trend", {}).get("short_term"),
            "momentum": analysis_result.get("momentum", {}).get("state"),
            "confidence": analysis_result.get("confidence"),
        }
    if node_name == "fundamental":
        return {
            "effective_trade_date": analysis_result.get("effective_trade_date"),
            "growth": analysis_result.get("growth", {}).get("state"),
            "valuation": analysis_result.get("valuation", {}).get("state"),
            "company_type": analysis_result.get("company_profile", {}).get("company_type"),
            "confidence": analysis_result.get("confidence"),
        }
    if node_name == "event_news":
        return {
            "effective_trade_date": analysis_result.get("effective_trade_date"),
            "event_state": analysis_result.get("event_overview", {}).get("state"),
            "company_events": len(analysis_result.get("company_specific_events", [])),
            "industry_events": len(analysis_result.get("industry_macro_events", [])),
        }
    if node_name == "sector_flow":
        return {
            "effective_trade_date": analysis_result.get("effective_trade_date"),
            "theme_strength": analysis_result.get("theme_strength", {}).get("state"),
            "theme_heat": analysis_result.get("theme_heat", {}).get("state"),
            "stock_role": analysis_result.get("stock_role_in_theme", {}).get("state"),
        }
    if node_name == "strategy_style":
        return {
            "effective_date": analysis_result.get("effective_date"),
            "primary_strategy": analysis_result.get("primary_strategy", {}).get("type"),
            "holding_horizon": analysis_result.get("holding_horizon", {}).get("type"),
            "secondary_count": len(analysis_result.get("secondary_strategies", [])),
        }
    return {"keys": sorted(result.keys())}


class StructuredAnalysisGraph:
    def __init__(self, config: dict[str, Any] | None = None, debug: bool = True):
        self.config = config or DEFAULT_CONFIG.copy()
        self.debug = debug
        self.technical_agent = TechnicalAgent(config=self.config, debug=debug)
        self.fundamental_agent = FundamentalAgent(config=self.config, debug=debug)
        self.event_news_agent = EventNewsAgent(config=self.config, debug=debug)
        self.sector_flow_agent = SectorFlowAgent(config=self.config, debug=debug)
        self.strategy_style_agent = StrategyStyleAgent(config=self.config, debug=debug)
        self._graph_trace: AgentTraceBuilder | None = None
        self._artifact_store = TraceArtifactStore(self.config)
        self.graph = self._build_graph()

    def _latest_agent_trace(self, node_name: str) -> dict[str, Any] | None:
        agent_map = {
            "technical": self.technical_agent,
            "fundamental": self.fundamental_agent,
            "event_news": self.event_news_agent,
            "sector_flow": self.sector_flow_agent,
            "strategy_style": self.strategy_style_agent,
        }
        agent = agent_map.get(node_name)
        return getattr(agent, "last_trace", None) if agent is not None else None

    def _start_graph_step(self, node_name: str, input_summary: dict[str, Any]) -> str | None:
        if self._graph_trace is None:
            return None
        return self._graph_trace.start_step(
            name=node_name,
            step_type="node",
            input_payload=input_summary,
        )

    def _end_graph_step(
        self,
        step_id: str | None,
        *,
        output_summary: dict[str, Any] | None = None,
        error: Exception | None = None,
        raw_debug: Any = None,
    ) -> None:
        if self._graph_trace is None or step_id is None:
            return
        if error is None:
            self._graph_trace.end_step(step_id, output_payload=output_summary or {})
            step = self._graph_trace.steps[-1]
            if raw_debug is not None:
                step.setdefault("artifacts", {})
                step["artifacts"]["raw_debug"] = _snapshot_for_trace(raw_debug)
            return
        self._graph_trace.fail_step(step_id, error)
        step = self._graph_trace.steps[-1]
        if raw_debug is not None:
            step.setdefault("artifacts", {})
            step["artifacts"]["raw_debug"] = _snapshot_for_trace(raw_debug)

    def _build_graph(self):
        workflow = StateGraph(StructuredAnalysisState)
        workflow.add_node("company_context", self._company_context_node)
        workflow.add_node("technical", self._technical_node)
        workflow.add_node("fundamental", self._fundamental_node)
        workflow.add_node("event_news", self._event_news_node)
        workflow.add_node("sector_flow", self._sector_flow_node)
        workflow.add_node("collect_results", self._collect_results_node)
        workflow.add_node("strategy_style", self._strategy_style_node)

        workflow.add_edge(START, "company_context")
        workflow.add_conditional_edges("company_context", self._route_after_node, {"continue": "technical", "end": END})
        workflow.add_edge("company_context", "fundamental")
        workflow.add_edge("company_context", "event_news")
        workflow.add_edge("company_context", "sector_flow")
        workflow.add_edge(["technical", "fundamental", "event_news", "sector_flow"], "collect_results")
        workflow.add_conditional_edges("collect_results", self._route_after_node, {"continue": "strategy_style", "end": END})
        workflow.add_edge("strategy_style", END)
        return workflow.compile()

    def _route_after_node(self, state: dict[str, Any]) -> str:
        return "end" if state.get("failure") else "continue"

    def _company_context_node(self, state: dict[str, Any]) -> dict[str, Any]:
        node_name = "company_context"
        started_at = _now_ts()
        input_summary = _node_input_summary(state, node_name)
        graph_step_id = self._start_graph_step(node_name, input_summary)
        try:
            company_context = build_company_context(
                state["ticker"],
                state["analysis_date"],
                date_mode="natural_day",
            )
            output_summary = {
                "identity": _snapshot_for_trace(company_context.get("identity")),
                "classification": _snapshot_for_trace(company_context.get("classification")),
                "analysis_time": _snapshot_for_trace(company_context.get("analysis_time")),
            }
            trace_entry = _trace_success(node_name, started_at, input_summary, output_summary)
            updates = {"company_context": company_context, "failure": None}
            self._end_graph_step(
                graph_step_id,
                output_summary={
                    "market": company_context.get("identity", {}).get("market"),
                    "exchange": company_context.get("identity", {}).get("exchange"),
                },
            )
        except Exception as error:
            trace_entry = _trace_error(node_name, started_at, input_summary, error)
            updates = {"failure": {"node": node_name, "message": str(error)}}
            updates.update(_append_failure(node_name, str(error)))
            self._end_graph_step(graph_step_id, error=error)
        updates.update(_append_trace(trace_entry))
        return updates

    def _technical_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._run_agent_node(
            state=state,
            node_name="technical",
            call=lambda: self.technical_agent.analyze(
                state["ticker"],
                state["analysis_date"],
                company_context=state.get("company_context"),
            ),
            result_key="technical_result",
            context_key=None,
        )

    def _fundamental_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._run_agent_node(
            state=state,
            node_name="fundamental",
            call=lambda: self.fundamental_agent.analyze(
                state["ticker"],
                state["analysis_date"],
                company_context=state.get("company_context"),
            ),
            result_key="fundamental_result",
            context_key=None,
        )

    def _event_news_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._run_agent_node(
            state=state,
            node_name="event_news",
            call=lambda: self.event_news_agent.analyze(
                state["ticker"],
                state["analysis_date"],
                company_context=state.get("company_context"),
            ),
            result_key="event_news_result",
            context_key=None,
        )

    def _sector_flow_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._run_agent_node(
            state=state,
            node_name="sector_flow",
            call=lambda: self.sector_flow_agent.analyze(
                state["ticker"],
                state["analysis_date"],
            ),
            result_key="sector_flow_result",
            context_key=None,
        )

    def _strategy_style_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._run_agent_node(
            state=state,
            node_name="strategy_style",
            call=lambda: self.strategy_style_agent.analyze(
                ticker=state["ticker"],
                analysis_date=state["analysis_date"],
                company_context=state["company_context"],
                technical_analysis_result=state["technical_result"]["analysis_result"],
                fundamental_analysis_result=state["fundamental_result"]["analysis_result"],
                event_analysis_result=state["event_news_result"]["analysis_result"],
                sector_flow_analysis_result=state["sector_flow_result"]["analysis_result"],
            ),
            result_key="strategy_style_result",
            context_key=None,
        )

    def _collect_results_node(self, state: dict[str, Any]) -> dict[str, Any]:
        node_name = "collect_results"
        started_at = _now_ts()
        input_summary = {
            "failures_count": len(state.get("failures", [])),
            "has_technical": state.get("technical_result") is not None,
            "has_fundamental": state.get("fundamental_result") is not None,
            "has_event_news": state.get("event_news_result") is not None,
            "has_sector_flow": state.get("sector_flow_result") is not None,
        }
        graph_step_id = self._start_graph_step(node_name, input_summary)
        missing = [
            key
            for key in ("technical_result", "fundamental_result", "event_news_result", "sector_flow_result")
            if state.get(key) is None
        ]
        failures = list(state.get("failures", []))
        failure = failures[0] if failures else None
        if failure is None and missing:
            failure = {"node": node_name, "message": f"Missing required results: {', '.join(missing)}"}

        output_summary = {"missing_results": missing, "selected_failure": failure}
        trace_entry = _trace_success(node_name, started_at, input_summary, output_summary)
        self._end_graph_step(graph_step_id, output_summary=output_summary)
        updates: dict[str, Any] = {"failure": failure}
        updates.update(_append_trace(trace_entry))
        return updates

    def _run_agent_node(
        self,
        *,
        state: dict[str, Any],
        node_name: str,
        call,
        result_key: str,
        context_key: str | None,
    ) -> dict[str, Any]:
        started_at = _now_ts()
        input_summary = _node_input_summary(state, node_name)
        graph_step_id = self._start_graph_step(node_name, input_summary)
        try:
            result = call()
            updates: dict[str, Any] = {result_key: result}
            if context_key and result.get("company_context") is not None:
                updates[context_key] = result["company_context"]
            output_summary = _build_output_summary(node_name, result)
            raw_debug = result.get("trace") or result.get("debug_trace") or result.get("raw_response")
            trace_entry = _trace_success(
                node_name=node_name,
                started_at=started_at,
                input_summary=input_summary,
                output_summary=output_summary,
                raw_debug=_snapshot_for_trace(raw_debug),
            )
            self._end_graph_step(graph_step_id, output_summary=output_summary, raw_debug=raw_debug)
        except Exception as error:
            trace_entry = _trace_error(node_name, started_at, input_summary, error)
            latest_trace = self._latest_agent_trace(node_name)
            if latest_trace is not None:
                trace_entry["raw_debug"] = _snapshot_for_trace(latest_trace)
            self._end_graph_step(graph_step_id, error=error, raw_debug=latest_trace)
            updates = _append_failure(node_name, str(error))
        updates.update(_append_trace(trace_entry))
        return updates

    def run(self, ticker: str, analysis_date: str) -> dict[str, Any]:
        self._graph_trace = AgentTraceBuilder(
            agent_name="StructuredAnalysisGraph",
            agent_type="graph",
            config=self.config,
            input_summary={"ticker": ticker, "analysis_date": analysis_date},
        )
        initial_state: StructuredAnalysisState = {
            "ticker": ticker,
            "analysis_date": analysis_date,
            "trace": [],
            "failures": [],
            "failure": None,
            "company_context": None,
            "technical_result": None,
            "fundamental_result": None,
            "event_news_result": None,
            "sector_flow_result": None,
            "strategy_style_result": None,
            "run_trace": None,
            "trace_artifacts": None,
        }
        final_state = self.graph.invoke(initial_state)
        run_error = None
        if final_state.get("failure"):
            run_error = RuntimeError(str(final_state["failure"].get("message")))
        output_summary = {
            "failure": final_state.get("failure"),
            "has_technical": final_state.get("technical_result") is not None,
            "has_fundamental": final_state.get("fundamental_result") is not None,
            "has_event_news": final_state.get("event_news_result") is not None,
            "has_sector_flow": final_state.get("sector_flow_result") is not None,
            "has_strategy_style": final_state.get("strategy_style_result") is not None,
        }
        run_trace = self._graph_trace.finish(output_summary=output_summary, error=run_error)
        trace_artifacts = self._artifact_store.persist_run(run_trace, final_state)
        if trace_artifacts is not None:
            for step in run_trace.get("steps", []):
                node_artifacts = trace_artifacts.get("nodes", {}).get(str(step.get("name")), {})
                if node_artifacts:
                    step.setdefault("artifacts", {})
                    step["artifacts"].update(node_artifacts)
                step.get("artifacts", {}).pop("raw_debug", None)
            if trace_artifacts.get("run_trace"):
                self._artifact_store.rewrite_ref(trace_artifacts["run_trace"], run_trace)
        final_state["run_trace"] = run_trace
        final_state["trace_artifacts"] = trace_artifacts
        final_state["trace"] = [
            {
                **entry,
                "raw_debug": None,
                "artifacts": (trace_artifacts or {}).get("nodes", {}).get(str(entry.get("node")), {}),
            }
            for entry in final_state.get("trace", [])
        ]
        self._graph_trace = None
        return final_state
