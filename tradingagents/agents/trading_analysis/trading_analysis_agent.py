from __future__ import annotations

from typing import Any, Callable

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.structured_analysis_graph import StructuredAnalysisGraph


class TradingAnalysisAgent:
    def __init__(self, config: dict[str, Any] | None = None, debug: bool = True):
        self.config = config or DEFAULT_CONFIG.copy()
        self.debug = debug
        self.graph = StructuredAnalysisGraph(config=self.config, debug=debug)

    def analyze(
        self,
        ticker: str,
        analysis_date: str,
        on_run_created: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        state = self.graph.run(ticker=ticker, analysis_date=analysis_date, on_run_created=on_run_created)
        return {
            "ticker": ticker,
            "analysis_date": analysis_date,
            "failure": state.get("failure"),
            "run_trace": state.get("run_trace"),
            "trace_artifacts": state.get("trace_artifacts"),
            "trace": state.get("trace", []),
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
        }
