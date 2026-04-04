from __future__ import annotations

import argparse
from pathlib import Path
import sys

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.tracing.api import create_trace_viewer_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TradingAgents trace viewer backend API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    app = create_trace_viewer_app(DEFAULT_CONFIG.copy())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
