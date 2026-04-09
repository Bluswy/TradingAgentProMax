from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradingagents.agents.trading_analysis import TradingAnalysisAgent


def _json_default(value):
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _build_summary(result: dict) -> dict:
    ui_summaries = result.get("ui_summaries") or {}
    strategy_style = ui_summaries.get("strategy_style") or {}
    strategy_decision = ui_summaries.get("strategy_decision") or {}
    company_report = ui_summaries.get("company_report") or {}
    final_report = result.get("final_report_result") or {}
    run_trace = result.get("run_trace") or {}

    return {
        "ticker": result.get("ticker"),
        "analysis_date": result.get("analysis_date"),
        "failure": result.get("failure"),
        "graph_duration_ms": run_trace.get("duration_ms"),
        "has_technical": result.get("technical_result") is not None,
        "has_fundamental": result.get("fundamental_result") is not None,
        "has_event_news": result.get("event_news_result") is not None,
        "has_sector_flow": result.get("sector_flow_result") is not None,
        "has_strategy_style": result.get("strategy_style_result") is not None,
        "has_strategy_decision": result.get("strategy_decision_result") is not None,
        "has_company_report": result.get("company_report_result") is not None,
        "has_final_report": result.get("final_report_result") is not None,
        "ui_summary_schema_version": strategy_style.get("schema_version"),
        "primary_strategy": strategy_style.get("primary_label"),
        "decision_action": strategy_decision.get("primary_label"),
        "decision_priority": strategy_decision.get("secondary_label"),
        "report_title": final_report.get("report_title") or company_report.get("primary_label"),
        "final_report_markdown_length": len(final_report.get("report_markdown", "")),
        "trace_nodes": [step.get("node") for step in result.get("trace", [])],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run structured trading analysis graph with full trace.")
    parser.add_argument("--ticker", required=True, help="Ticker, e.g. 601872.SH or 9926.HK")
    parser.add_argument("--date", required=True, help="Analysis date in YYYY-MM-DD")
    parser.add_argument("--output", help="Optional output path for JSON trace")
    parser.add_argument("--markdown-output", help="Optional output path for final report markdown")
    args = parser.parse_args()

    agent = TradingAnalysisAgent(debug=True)
    result = agent.analyze(args.ticker, args.date)
    summary = _build_summary(result)

    payload = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")

    if args.markdown_output:
        report_markdown = ((result.get("final_report_result") or {}).get("report_markdown", "")).strip()
        output_path = Path(args.markdown_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_markdown, encoding="utf-8")

    if args.output or args.markdown_output:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    else:
        print(payload)


if __name__ == "__main__":
    main()
