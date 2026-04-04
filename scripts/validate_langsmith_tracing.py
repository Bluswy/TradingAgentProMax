from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradingagents.agents.trading_analysis import TradingAnalysisAgent
from tradingagents.default_config import DEFAULT_CONFIG


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate LangSmith tracing with a structured analysis run.")
    parser.add_argument("--ticker", default="601677.SH")
    parser.add_argument("--date", default="2026-03-29")
    args = parser.parse_args()

    has_key = bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))
    if not has_key:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "missing_langsmith_api_key",
                    "hint": "Set LANGSMITH_API_KEY or LANGCHAIN_API_KEY, then rerun this script.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    config = deepcopy(DEFAULT_CONFIG)
    config["langsmith_enabled"] = True

    agent = TradingAnalysisAgent(config=config, debug=True)
    result = agent.analyze(args.ticker, args.date)
    print(
        json.dumps(
            {
                "status": "ok",
                "ticker": args.ticker,
                "analysis_date": args.date,
                "run_id": (result.get("run_trace") or {}).get("run_id"),
                "langsmith_enabled": (result.get("run_trace") or {}).get("observability", {}).get("langsmith_enabled"),
                "langsmith_project_name": (result.get("run_trace") or {}).get("observability", {}).get("langsmith_project_name"),
                "trace_artifacts": result.get("trace_artifacts"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
