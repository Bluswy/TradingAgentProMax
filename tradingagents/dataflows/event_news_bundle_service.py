from __future__ import annotations

from datetime import datetime
from typing import Any

from tradingagents.agents.event_news.query_planner import EventQueryPlanner
from tradingagents.dataflows.config import get_config
from .mx_search_provider import (
    search_mx_queries,
    search_mx_custom_event_news,
)
from .tushare_provider import _normalize_symbol, _read_or_query, _require_tushare


def _fetch_stock_basic(ts_code: str) -> dict[str, Any]:
    pro = _require_tushare()
    basic = _read_or_query("stock_basic", {"ts_code": ts_code}, lambda: pro.stock_basic(ts_code=ts_code))
    if basic.empty:
        return {}
    row = basic.head(1).iloc[0]
    return {
        "name": row.get("name"),
        "industry": row.get("industry"),
        "market": row.get("market"),
        "list_date": row.get("list_date"),
    }


def _build_event_compact_signals(company_news_count: int, macro_news_count: int) -> dict[str, str]:
    total = company_news_count + macro_news_count
    if total >= 14:
        density = "high"
    elif total >= 6:
        density = "medium"
    else:
        density = "low"

    return {
        "company_event_bias": "unknown",
        "macro_event_bias": "unknown",
        "event_density": density,
        "policy_sensitivity": "medium",
        "earnings_catalyst_state": "unknown",
        "risk_event_level": "unknown",
    }


def build_event_news_data_bundle(
    ticker: str,
    analysis_date: str,
    company_news_limit: int = 8,
    macro_news_limit: int = 8,
) -> dict[str, Any]:
    ts_code = _normalize_symbol(ticker)
    requested_date = datetime.strptime(analysis_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    effective_date = requested_date

    meta = _fetch_stock_basic(ts_code)
    company_type = "general_corporate"
    try:
        from tradingagents.dataflows.fundamental_bundle_service import _detect_company_profile

        company_type = _detect_company_profile(meta.get("industry")).get("company_type", "general_corporate")
    except Exception:
        company_type = "general_corporate"

    planner = EventQueryPlanner(config=get_config())
    planner_context = {
        "ticker": ts_code,
        "company_name": meta.get("name") or ts_code,
        "analysis_date": effective_date,
        "industry": meta.get("industry") or "",
        "company_type": company_type,
        "business_hint": None,
    }
    query_plan = planner.plan(planner_context)

    company_news = search_mx_queries(
        query_plan.get("company_queries", []),
        limit_per_query=max(company_news_limit * 2, 10),
        rerank_mode="company",
        ticker=ts_code,
        company_name=meta.get("name") or ts_code,
        final_limit=company_news_limit,
    )
    industry_news = search_mx_queries(
        query_plan.get("industry_queries", []),
        limit_per_query=max(macro_news_limit * 2, 10),
        rerank_mode="macro",
        industry=meta.get("industry") or "",
        final_limit=macro_news_limit,
    )
    global_news = search_mx_queries(
        query_plan.get("global_event_queries", []),
        limit_per_query=max(macro_news_limit * 2, 10),
        rerank_mode="macro",
        industry=meta.get("industry") or "",
        final_limit=macro_news_limit,
    )
    macro_news_results = []
    for group in (industry_news.get("results", []), global_news.get("results", [])):
        for item in group:
            if item not in macro_news_results:
                macro_news_results.append(item)
    macro_news_results = macro_news_results[:macro_news_limit]

    return {
        "ticker": ts_code,
        "requested_date": requested_date,
        "effective_trade_date": effective_date,
        "meta": meta,
        "company_news": company_news.get("results", []),
        "macro_news": macro_news_results,
        "announcements": [],
        "market_events": [],
        "event_compact_signals": _build_event_compact_signals(
            company_news_count=len(company_news.get("results", [])),
            macro_news_count=len(macro_news_results),
        ),
        "query_plan": query_plan,
        "debug_trace": {
            "planner_context": planner_context,
            "query_plan": query_plan,
            "company_search": company_news,
            "industry_search": industry_news,
            "global_search": global_news,
        },
        "data_quality": {
            "company_news_count": len(company_news.get("results", [])),
            "macro_news_count": len(macro_news_results),
            "announcements_count": 0,
            "market_events_count": 0,
            "source": "mx_search+tushare",
        },
    }


def get_company_event_news(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_event_news_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "company_news": bundle["company_news"],
    }


def get_macro_policy_news(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_event_news_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "macro_news": bundle["macro_news"],
    }


def search_custom_event_news(query: str, limit: int = 10) -> dict[str, Any]:
    return search_mx_custom_event_news(query=query, limit=limit)
