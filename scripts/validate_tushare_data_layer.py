from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradingagents.dataflows.tushare_provider import (
    get_tushare_balance_sheet,
    get_tushare_cashflow,
    get_tushare_fundamentals,
    get_tushare_income_statement,
    get_tushare_indicator,
    get_tushare_stock_data,
)


DEFAULT_TICKER = "601677.SH"  # 明泰铝业
DEFAULT_TRADE_DATE = datetime.now().strftime("%Y-%m-%d")
DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_MARKET_WINDOW_DAYS = 120
DEFAULT_INDICATORS = [
    "close_50_sma",
    "close_200_sma",
    "close_10_ema",
    "macd",
    "macds",
    "macdh",
    "rsi",
    "atr",
    "boll",
    "boll_ub",
    "boll_lb",
    "vwma",
    "mfi",
]


@dataclass
class CheckResult:
    name: str
    success: bool
    details: str


def _print_result(result: CheckResult) -> None:
    status = "PASS" if result.success else "FAIL"
    print(f"[{status}] {result.name}")
    print(result.details)
    print("-" * 80)


def _expect_contains(name: str, payload: str, required_tokens: list[str]) -> CheckResult:
    missing = [token for token in required_tokens if token not in payload]
    if missing:
        return CheckResult(
            name=name,
            success=False,
            details=f"Missing required tokens: {missing}\nPreview:\n{payload[:800]}",
        )
    return CheckResult(
        name=name,
        success=True,
        details=f"Output length={len(payload)}\nPreview:\n{payload[:800]}",
    )


def _run_check(name: str, fn) -> CheckResult:
    try:
        return fn()
    except Exception as exc:
        return CheckResult(
            name=name,
            success=False,
            details=f"Raised exception: {type(exc).__name__}: {exc}",
        )


def validate_stock_data(ticker: str, trade_date: str) -> CheckResult:
    start_date = (
        datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=DEFAULT_MARKET_WINDOW_DAYS)
    ).strftime("%Y-%m-%d")
    return _run_check(
        "stock_data",
        lambda: _expect_contains(
            "stock_data",
            get_tushare_stock_data(ticker, start_date, trade_date),
            ["# Tushare qfq stock data", "Date,Open,High,Low,Close", "Up Limit", "Down Limit"],
        ),
    )


def validate_indicators(ticker: str, trade_date: str, lookback_days: int) -> list[CheckResult]:
    results = []
    for indicator in DEFAULT_INDICATORS:
        results.append(
            _run_check(
                f"indicator::{indicator}",
                lambda indicator=indicator: _expect_contains(
                    f"indicator::{indicator}",
                    get_tushare_indicator(ticker, indicator, trade_date, lookback_days),
                    [f"## {indicator} values", trade_date],
                ),
            )
        )
    return results


def validate_fundamentals(ticker: str, trade_date: str) -> CheckResult:
    return _run_check(
        "fundamentals_overview",
        lambda: _expect_contains(
            "fundamentals_overview",
            get_tushare_fundamentals(ticker, trade_date),
            [f"## Fundamentals overview for {ticker}", "TS Code", "Name"],
        ),
    )


def validate_statements(ticker: str, trade_date: str) -> list[CheckResult]:
    results = []
    statement_calls = [
        ("balance_sheet", get_tushare_balance_sheet),
        ("cashflow", get_tushare_cashflow),
        ("income_statement", get_tushare_income_statement),
    ]
    for name, func in statement_calls:
        results.append(
            _run_check(
                name,
                lambda name=name, func=func: _expect_contains(
                    name,
                    func(ticker, "quarterly", trade_date),
                    [f"## {'balancesheet' if name == 'balance_sheet' else 'cashflow' if name == 'cashflow' else 'income'} data for {ticker}"],
                ),
            )
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Tushare-backed data layer for A-share analysis with recent monthly data."
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER, help="A-share ts_code, defaults to 601677.SH")
    parser.add_argument(
        "--trade-date",
        default=DEFAULT_TRADE_DATE,
        help="Trade date in YYYY-MM-DD format, defaults to today so the script validates recent months of data",
    )
    parser.add_argument(
        "--lookback-days",
        default=DEFAULT_LOOKBACK_DAYS,
        type=int,
        help="Indicator lookback days, defaults to 90 for recent multi-month validation",
    )
    args = parser.parse_args()

    results: list[CheckResult] = []
    results.append(validate_stock_data(args.ticker, args.trade_date))
    results.extend(validate_indicators(args.ticker, args.trade_date, args.lookback_days))
    results.append(validate_fundamentals(args.ticker, args.trade_date))
    results.extend(validate_statements(args.ticker, args.trade_date))

    failures = 0
    for result in results:
        _print_result(result)
        if not result.success:
            failures += 1

    print(f"Completed {len(results)} checks, failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
