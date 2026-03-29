from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.technical_bundle_service import (
    get_benchmark_relative_strength as _get_benchmark_relative_strength,
    get_extended_price_window as _get_extended_price_window,
    get_moneyflow_context as _get_moneyflow_context,
    get_price_structure_levels as _get_price_structure_levels,
)


@tool
def get_extended_price_window(
    ticker: Annotated[str, "A股ts_code，例如601677.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
    lookback_trading_days: Annotated[int, "回看交易日数量"] = 180,
) -> str:
    """补充更长周期的前复权行情和技术数据。"""
    return json.dumps(
        _get_extended_price_window(
            ticker=ticker,
            analysis_date=analysis_date,
            lookback_trading_days=lookback_trading_days,
        ),
        ensure_ascii=False,
    )


@tool
def get_benchmark_relative_strength(
    ticker: Annotated[str, "A股ts_code，例如601677.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
    benchmark_code: Annotated[str, "基准指数代码，默认沪深300"] = "000300.SH",
) -> str:
    """补充相对基准强弱数据。"""
    return json.dumps(
        _get_benchmark_relative_strength(
            ticker=ticker,
            analysis_date=analysis_date,
            benchmark_code=benchmark_code,
        ),
        ensure_ascii=False,
    )


@tool
def get_price_structure_levels(
    ticker: Annotated[str, "A股ts_code，例如601677.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充价格结构关键位，例如20/60/90日高低点。"""
    return json.dumps(
        _get_price_structure_levels(ticker=ticker, analysis_date=analysis_date),
        ensure_ascii=False,
    )


@tool
def get_moneyflow_context(
    ticker: Annotated[str, "A股ts_code，例如601677.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充资金流和活跃度上下文。"""
    return json.dumps(
        _get_moneyflow_context(ticker=ticker, analysis_date=analysis_date),
        ensure_ascii=False,
    )


TECHNICAL_TOOLS = [
    get_extended_price_window,
    get_benchmark_relative_strength,
    get_price_structure_levels,
    get_moneyflow_context,
]
