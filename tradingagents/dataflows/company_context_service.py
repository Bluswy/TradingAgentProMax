from __future__ import annotations

from typing import Any

from .company_context import merge_company_context, new_company_context
from .fundamental_bundle_service import _detect_company_profile, _fetch_daily_basic_window
from .query_context_service import build_event_query_context
from .technical_bundle_service import normalize_trade_date
from .tushare_provider import _normalize_symbol, _read_or_query, _require_tushare


def _fetch_stock_basic_meta(ts_code: str) -> dict[str, Any]:
    pro = _require_tushare()
    basic = _read_or_query("stock_basic", {"ts_code": ts_code}, lambda: pro.stock_basic(ts_code=ts_code))
    if basic.empty:
        return {"name": ts_code, "industry": "", "market": "", "list_date": ""}
    row = basic.head(1).iloc[0]
    return {
        "name": row.get("name") or ts_code,
        "industry": row.get("industry") or "",
        "market": row.get("market") or "",
        "list_date": row.get("list_date") or "",
    }


def _infer_market_context(ts_code: str, effective_date: str, company_type: str) -> dict[str, Any]:
    try:
        daily_basic = _fetch_daily_basic_window(ts_code, effective_date)
    except Exception:
        daily_basic = None

    total_mv = None
    turnover_rate = None
    if daily_basic is not None and not daily_basic.empty:
        row = daily_basic.head(1).iloc[0]
        total_mv = row.get("total_mv")
        turnover_rate = row.get("turnover_rate")

    size_bucket = ""
    if total_mv is not None:
        try:
            total_mv = float(total_mv)
            if total_mv >= 20000000:
                size_bucket = "large_cap"
            elif total_mv >= 5000000:
                size_bucket = "mid_cap"
            else:
                size_bucket = "small_cap"
        except Exception:
            size_bucket = ""

    liquidity_bucket = ""
    if turnover_rate is not None:
        try:
            turnover_rate = float(turnover_rate)
            if turnover_rate >= 5:
                liquidity_bucket = "high"
            elif turnover_rate >= 1:
                liquidity_bucket = "medium"
            else:
                liquidity_bucket = "low"
        except Exception:
            liquidity_bucket = ""

    valuation_style = ""
    if company_type in {"cyclical_resources", "utilities_transport_infrastructure", "real_estate_construction"}:
        valuation_style = "cyclical"
    elif company_type in {"tmt_growth", "consumer_healthcare_growth"}:
        valuation_style = "growth"
    elif company_type == "financials":
        valuation_style = "financial"
    else:
        valuation_style = "general"

    return {
        "classification": {
            "style_tag": company_type,
            "size_bucket": size_bucket,
            "liquidity_bucket": liquidity_bucket,
        },
        "market_context": {
            "valuation_style": valuation_style,
            "market_attention_points": [],
            "trading_sensitivity": [],
        },
    }


def build_company_context(ticker: str, analysis_date: str, date_mode: str = "natural_day") -> dict[str, Any]:
    ts_code = _normalize_symbol(ticker)
    meta = _fetch_stock_basic_meta(ts_code)
    company_profile = _detect_company_profile(meta.get("industry"))

    if date_mode == "trade_day":
        time_info = normalize_trade_date(analysis_date)
        effective_date = time_info["effective_trade_date"]
        date_mode_value = "trade_day"
    else:
        effective_date = analysis_date
        date_mode_value = "natural_day"

    query_context = build_event_query_context(
        ticker=ts_code,
        analysis_date=effective_date,
        company_name=meta.get("name") or ts_code,
        industry=meta.get("industry") or "",
        company_type=company_profile.get("company_type") or "",
    )

    sub_industry = ""
    index_memberships = query_context.get("index_memberships") or []
    if index_memberships:
        sub_industry = index_memberships[-1]
    elif meta.get("industry"):
        sub_industry = str(meta["industry"])

    base = new_company_context()
    updates = {
        "identity": {
            "ticker": ts_code,
            "company_name": meta.get("name") or ts_code,
            "exchange": ts_code.split(".")[-1],
            "market": "A_share",
        },
        "analysis_time": {
            "requested_date": analysis_date,
            "effective_date": effective_date,
            "date_mode": date_mode_value,
        },
        "classification": {
            "industry": meta.get("industry") or "",
            "company_type": company_profile.get("company_type") or "",
        },
        "business_context": {
            "sub_industry": sub_industry,
            "business_model": query_context.get("main_business") or "",
            "company_intro": query_context.get("company_intro") or "",
            "core_products": list(query_context.get("main_business_items") or [])[:5],
            "main_business_items": list(query_context.get("main_business_items") or []),
            "demand_drivers": [],
            "cost_drivers": [],
            "policy_drivers": [],
            "global_risk_drivers": [],
        },
        "search_context": {
            "search_aliases": list(query_context.get("search_aliases") or []),
            "seed_titles": [],
            "ths_member_codes": list(query_context.get("ths_member_codes") or []),
            "ths_concepts": list(query_context.get("ths_concepts") or []),
            "index_memberships": list(query_context.get("index_memberships") or []),
        },
        "data_quality": {
            "source_summary": {
                "stock_basic": True,
                "stock_company": bool(query_context.get("stock_company")),
                "fina_mainbz": bool(query_context.get("main_business_items")),
                "ths_member": bool(query_context.get("ths_member_codes")),
                "index_member_all": bool(query_context.get("index_memberships")),
            }
        },
    }
    updates = merge_company_context(updates, _infer_market_context(ts_code, effective_date, company_profile.get("company_type") or ""))
    return merge_company_context(base, updates)


def update_company_context_with_technical(
    company_context: dict[str, Any],
    analysis_result: dict[str, Any],
) -> dict[str, Any]:
    return merge_company_context(
        company_context,
        {
            "technical_context": {
                "trend": analysis_result.get("trend", {}),
                "momentum": analysis_result.get("momentum", {}),
                "volatility": analysis_result.get("volatility", {}),
                "volume_confirmation": analysis_result.get("volume_confirmation", {}),
                "relative_strength": analysis_result.get("relative_strength", {}),
                "technical_compact_signals": analysis_result.get("indicator_snapshot", {}),
                "key_levels": analysis_result.get("key_levels", {}),
                "signals": analysis_result.get("signals", []),
                "confidence": analysis_result.get("confidence"),
                "module_brief": analysis_result.get("module_brief", {}),
                "module_summary_items": analysis_result.get("module_summary_items", []),
                "technical_summary_zh": analysis_result.get("technical_summary_zh", ""),
            }
        },
    )


def update_company_context_with_fundamental(
    company_context: dict[str, Any],
    analysis_result: dict[str, Any],
) -> dict[str, Any]:
    return merge_company_context(
        company_context,
        {
            "fundamental_context": {
                "company_profile": analysis_result.get("company_profile", {}),
                "growth": analysis_result.get("growth", {}),
                "profitability": analysis_result.get("profitability", {}),
                "cashflow_quality": analysis_result.get("cashflow_quality", {}),
                "balance_sheet_health": analysis_result.get("balance_sheet_health", {}),
                "valuation": analysis_result.get("valuation", {}),
                "fundamental_compact_signals": analysis_result.get("fundamental_compact_signals", {}),
                "financial_snapshot": analysis_result.get("financial_snapshot", {}),
                "core_risks": analysis_result.get("core_risks", []),
                "fundamental_signals": analysis_result.get("fundamental_signals", []),
                "confidence": analysis_result.get("confidence"),
                "module_brief": analysis_result.get("module_brief", {}),
                "module_summary_items": analysis_result.get("module_summary_items", []),
                "fundamental_summary_zh": analysis_result.get("fundamental_summary_zh", ""),
            }
        },
    )


def update_company_context_with_event(
    company_context: dict[str, Any],
    analysis_result: dict[str, Any],
) -> dict[str, Any]:
    return merge_company_context(
        company_context,
        {
            "event_context": {
                "event_overview": analysis_result.get("event_overview", {}),
                "event_compact_signals": analysis_result.get("event_compact_signals", {}),
                "event_context_snapshot": analysis_result.get("event_context_snapshot", {}),
                "event_chain": analysis_result.get("event_chain", {}),
                "key_catalysts": analysis_result.get("key_catalysts", []),
                "key_risks": analysis_result.get("key_risks", []),
                "tracking_points": analysis_result.get("tracking_points", []),
                "confidence": analysis_result.get("event_overview", {}).get("confidence"),
                "module_brief": analysis_result.get("module_brief", {}),
                "module_summary_items": analysis_result.get("module_summary_items", []),
                "event_summary_zh": analysis_result.get("event_summary_zh", ""),
            }
        },
    )
