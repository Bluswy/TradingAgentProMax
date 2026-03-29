from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.fundamental_bundle_service import (
    get_balance_sheet_summary as _get_balance_sheet_summary,
    get_cashflow_summary as _get_cashflow_summary,
    get_income_statement_summary as _get_income_statement_summary,
    get_latest_financial_snapshot as _get_latest_financial_snapshot,
    get_multi_period_financial_trends as _get_multi_period_financial_trends,
    get_valuation_snapshot as _get_valuation_snapshot,
)


@tool
def get_latest_financial_snapshot(
    ticker: Annotated[str, "A股ts_code，例如601899.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充最近一期核心财务快照。"""
    return json.dumps(_get_latest_financial_snapshot(ticker, analysis_date), ensure_ascii=False)


@tool
def get_valuation_snapshot(
    ticker: Annotated[str, "A股ts_code，例如601899.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充估值与市值快照。"""
    return json.dumps(_get_valuation_snapshot(ticker, analysis_date), ensure_ascii=False)


@tool
def get_income_statement_summary(
    ticker: Annotated[str, "A股ts_code，例如601899.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充利润表摘要。"""
    return json.dumps(_get_income_statement_summary(ticker, analysis_date), ensure_ascii=False)


@tool
def get_balance_sheet_summary(
    ticker: Annotated[str, "A股ts_code，例如601899.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充资产负债表摘要。"""
    return json.dumps(_get_balance_sheet_summary(ticker, analysis_date), ensure_ascii=False)


@tool
def get_cashflow_summary(
    ticker: Annotated[str, "A股ts_code，例如601899.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充现金流量表摘要。"""
    return json.dumps(_get_cashflow_summary(ticker, analysis_date), ensure_ascii=False)


@tool
def get_multi_period_financial_trends(
    ticker: Annotated[str, "A股ts_code，例如601899.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充多期财务趋势和公司类型信息。"""
    return json.dumps(_get_multi_period_financial_trends(ticker, analysis_date), ensure_ascii=False)


FUNDAMENTAL_TOOLS = [
    get_latest_financial_snapshot,
    get_valuation_snapshot,
    get_income_statement_summary,
    get_balance_sheet_summary,
    get_cashflow_summary,
    get_multi_period_financial_trends,
]
