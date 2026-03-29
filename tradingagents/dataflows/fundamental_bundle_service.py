from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .config import get_config
from .technical_bundle_service import normalize_trade_date
from .tushare_provider import _normalize_symbol, _read_or_query, _require_tushare


PROFILE_RULES = {
    "financials": {
        "industries": {"银行", "证券", "保险", "多元金融"},
        "analysis_focus": [
            "roe_pb_match",
            "asset_quality",
            "capital_adequacy",
            "balance_sheet_leverage",
        ],
        "deprioritized_metrics": ["gross_margin", "inventory_ratio"],
    },
    "cyclical_resources": {
        "industries": {
            "有色金属",
            "煤炭",
            "石油石化",
            "钢铁",
            "基础化工",
            "采掘",
            "铜",
            "黄金",
            "铝",
            "稀有金属",
            "小金属",
            "铅锌",
            "煤炭开采",
            "焦炭加工",
            "石油开采",
            "石油加工",
            "石油贸易",
            "普钢",
            "特种钢",
            "钢加工",
            "化工原料",
            "农药化肥",
            "化纤",
            "染料涂料",
            "橡胶",
            "塑料",
            "玻璃",
            "水泥",
            "陶瓷",
            "矿物制品",
            "造纸",
            "其他建材",
        },
        "analysis_focus": [
            "growth_cyclicality",
            "margin_sensitivity",
            "cashflow_strength",
            "capex_pressure",
            "valuation_cycle_position",
        ],
        "deprioritized_metrics": ["channel_efficiency"],
    },
    "industrial_manufacturing": {
        "industries": {
            "机械设备",
            "汽车",
            "电力设备",
            "电子",
            "国防军工",
            "家用电器",
            "专用机械",
            "农用机械",
            "化工机械",
            "工程机械",
            "机床制造",
            "机械基件",
            "轻工机械",
            "纺织机械",
            "电气设备",
            "电器仪表",
            "运输设备",
            "摩托车",
            "汽车整车",
            "汽车配件",
            "船舶",
            "航空",
            "家居用品",
            "广告包装",
            "纺织",
            "新型电力",
        },
        "analysis_focus": [
            "revenue_growth",
            "margin_stability",
            "inventory_receivables",
            "cashflow_conversion",
            "capex_discipline",
        ],
        "deprioritized_metrics": ["npl_ratio"],
    },
    "consumer_healthcare_growth": {
        "industries": {
            "食品饮料",
            "医药生物",
            "社会服务",
            "商贸零售",
            "美容护理",
            "农林牧渔",
            "中成药",
            "化学制药",
            "生物制药",
            "医药商业",
            "医疗保健",
            "白酒",
            "啤酒",
            "红黄酒",
            "乳制品",
            "软饮料",
            "食品",
            "饲料",
            "种植业",
            "渔业",
            "农业综合",
            "林业",
            "日用化工",
            "服饰",
            "文教休闲",
        },
        "analysis_focus": [
            "growth_stability",
            "brand_or_channel_efficiency",
            "margin_quality",
            "cashflow_conversion",
            "valuation_premium",
        ],
        "deprioritized_metrics": ["capital_adequacy"],
    },
    "consumer_services_retail": {
        "industries": {
            "其他商业",
            "商品城",
            "商贸代理",
            "批发业",
            "百货",
            "超市连锁",
            "电器连锁",
            "旅游景点",
            "旅游服务",
            "酒店餐饮",
            "汽车服务",
        },
        "analysis_focus": [
            "same_store_or_channel_trend",
            "demand_recovery",
            "inventory_and_cash_turn",
            "service_margin_stability",
            "valuation_vs_growth",
        ],
        "deprioritized_metrics": ["capital_adequacy"],
    },
    "tmt_growth": {
        "industries": {
            "计算机",
            "通信",
            "传媒",
            "电子元器件",
            "半导体",
            "互联网",
            "IT设备",
            "元器件",
            "电信运营",
            "通信设备",
            "软件服务",
            "影视音像",
            "出版业",
        },
        "analysis_focus": [
            "revenue_growth",
            "r_and_d_intensity",
            "operating_leverage",
            "cash_burn_or_conversion",
            "high_growth_valuation",
        ],
        "deprioritized_metrics": ["pb_as_primary_metric"],
    },
    "utilities_transport_infrastructure": {
        "industries": {
            "仓储物流",
            "供气供热",
            "公共交通",
            "公路",
            "机场",
            "港口",
            "空运",
            "水运",
            "铁路",
            "路桥",
            "火力发电",
            "水力发电",
            "水务",
            "环境保护",
        },
        "analysis_focus": [
            "regulated_or_capacity_returns",
            "utilization_and_throughput",
            "capex_and_cash_recovery",
            "balance_sheet_stability",
            "dividend_or_defensive_valuation",
        ],
        "deprioritized_metrics": ["inventory_ratio"],
    },
    "real_estate_construction": {
        "industries": {
            "全国地产",
            "区域地产",
            "园区开发",
            "房产服务",
            "建筑工程",
            "装修装饰",
        },
        "analysis_focus": [
            "sales_and_settlement",
            "cash_collection",
            "leverage_and_refinancing",
            "landbank_or_order_quality",
            "credit_cycle_valuation",
        ],
        "deprioritized_metrics": ["gross_margin_as_primary_metric"],
    },
    "general_corporate": {
        "industries": {"综合类"},
        "analysis_focus": [
            "revenue_growth",
            "profitability",
            "cashflow_conversion",
            "balance_sheet_health",
            "valuation",
        ],
        "deprioritized_metrics": [],
    },
}

DEFAULT_REPORT_PERIODS = 8
PROFILE_REPORT_PERIODS = {
    "cyclical_resources": 12,
}


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Any, digits: int = 6) -> float | None:
    number = _safe_float(value)
    return None if number is None else round(number, digits)


def _latest_record_before(df: pd.DataFrame, curr_date: str, date_columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df

    current_dt = pd.to_datetime(curr_date)
    working = df.copy()
    sort_col = None
    for col in date_columns:
        if col in working.columns:
            working[col] = pd.to_datetime(working[col], format="%Y%m%d", errors="coerce")
            if sort_col is None:
                sort_col = col
    if sort_col is None:
        return working.head(1)

    filtered = working[working[sort_col] <= current_dt]
    if filtered.empty:
        filtered = working
    return filtered.sort_values(sort_col, ascending=False).head(1)


def _records_before(df: pd.DataFrame, curr_date: str, date_columns: list[str], limit: int = 8) -> pd.DataFrame:
    if df.empty:
        return df

    current_dt = pd.to_datetime(curr_date)
    working = df.copy()
    sort_col = None
    for col in date_columns:
        if col in working.columns:
            working[col] = pd.to_datetime(working[col], format="%Y%m%d", errors="coerce")
            if sort_col is None:
                sort_col = col
    if sort_col is None:
        return working.head(limit)

    filtered = working[working[sort_col] <= current_dt]
    if filtered.empty:
        filtered = working
    return filtered.sort_values(sort_col, ascending=False).head(limit).reset_index(drop=True)


def _query_statement(endpoint: str, ts_code: str) -> pd.DataFrame:
    pro = _require_tushare()
    endpoint_func = getattr(pro, endpoint)
    return _read_or_query(endpoint, {"ts_code": ts_code}, lambda: endpoint_func(ts_code=ts_code))


def _fetch_stock_basic(ts_code: str) -> pd.Series:
    pro = _require_tushare()
    basic = _read_or_query("stock_basic", {"ts_code": ts_code}, lambda: pro.stock_basic(ts_code=ts_code))
    if basic.empty:
        return pd.Series(dtype=object)
    return basic.head(1).iloc[0]


def _fetch_daily_basic_window(ts_code: str, curr_date: str) -> pd.DataFrame:
    pro = _require_tushare()
    current_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (current_dt - timedelta(days=60)).strftime("%Y%m%d")
    end_date = current_dt.strftime("%Y%m%d")
    return _read_or_query(
        "daily_basic_window",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        lambda: pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date),
    )


def _detect_company_profile(industry: str | None) -> dict[str, Any]:
    for profile_name, config in PROFILE_RULES.items():
        if industry in config["industries"]:
            return {
                "company_type": profile_name,
                "industry": industry,
                "analysis_focus": config["analysis_focus"],
                "deprioritized_metrics": config["deprioritized_metrics"],
            }
    return {
        "company_type": "general_corporate",
        "industry": industry,
        "analysis_focus": [
            "revenue_growth",
            "profitability",
            "cashflow_conversion",
            "balance_sheet_health",
            "valuation",
        ],
        "deprioritized_metrics": [],
    }


def _resolve_report_periods(company_type: str) -> int:
    config = get_config()
    profile_overrides = config.get("fundamental_report_periods_by_type", {})
    if company_type in profile_overrides:
        return int(profile_overrides[company_type])
    if company_type in PROFILE_REPORT_PERIODS:
        return PROFILE_REPORT_PERIODS[company_type]
    return int(config.get("fundamental_report_periods", DEFAULT_REPORT_PERIODS))


def _extract_statement_summary(row: pd.Series, fields: dict[str, list[str]]) -> dict[str, float | None]:
    summary: dict[str, float | None] = {}
    for output_key, candidates in fields.items():
        value = None
        for candidate in candidates:
            if candidate in row.index:
                value = _round_or_none(row.get(candidate), 4)
                if value is not None:
                    break
        summary[output_key] = value
    return summary


def _build_financial_trends(
    fina_row: pd.Series,
    income_rows: pd.DataFrame,
    balance_rows: pd.DataFrame,
    cashflow_rows: pd.DataFrame,
) -> dict[str, Any]:
    latest_income = income_rows.iloc[0] if not income_rows.empty else pd.Series(dtype=object)
    latest_balance = balance_rows.iloc[0] if not balance_rows.empty else pd.Series(dtype=object)
    latest_cashflow = cashflow_rows.iloc[0] if not cashflow_rows.empty else pd.Series(dtype=object)

    operating_cashflow = _safe_float(
        latest_cashflow.get("n_cashflow_act")
        or latest_cashflow.get("n_cashflow_act")
    )
    net_profit = _safe_float(
        latest_income.get("n_income")
        or latest_income.get("n_income_attr_p")
        or latest_income.get("net_profit")
    )

    ocf_to_net_profit = None
    if operating_cashflow is not None and net_profit not in (None, 0):
        ocf_to_net_profit = round(operating_cashflow / net_profit, 6)

    return {
        "revenue_yoy": _round_or_none(fina_row.get("tr_yoy")),
        "net_profit_yoy": _round_or_none(fina_row.get("netprofit_yoy")),
        "deducted_net_profit_yoy": _round_or_none(fina_row.get("dt_netprofit_yoy")),
        "ocf_to_net_profit": ocf_to_net_profit,
        "gross_margin": _round_or_none(fina_row.get("grossprofit_margin")),
        "net_margin": _round_or_none(fina_row.get("netprofit_margin")),
        "roe": _round_or_none(fina_row.get("roe")),
        "roa": _round_or_none(fina_row.get("roa")),
        "debt_to_assets": _round_or_none(fina_row.get("debt_to_assets")),
        "current_ratio": _round_or_none(fina_row.get("current_ratio")),
        "quick_ratio": _round_or_none(fina_row.get("quick_ratio")),
        "receivables_ratio": None
        if _safe_float(latest_balance.get("total_assets")) in (None, 0)
        else round(_safe_float(latest_balance.get("accounts_receiv")) / _safe_float(latest_balance.get("total_assets")), 6),
        "inventory_ratio": None
        if _safe_float(latest_balance.get("total_assets")) in (None, 0)
        else round(_safe_float(latest_balance.get("inventories")) / _safe_float(latest_balance.get("total_assets")), 6),
    }


def _build_financial_snapshot(
    daily_row: pd.Series,
    fina_row: pd.Series,
    trends: dict[str, Any],
) -> dict[str, Any]:
    revenue_yoy = trends.get("revenue_yoy")
    net_profit_yoy = trends.get("net_profit_yoy")
    profit_minus_revenue_growth = None
    if revenue_yoy is not None and net_profit_yoy is not None:
        profit_minus_revenue_growth = round(net_profit_yoy - revenue_yoy, 6)

    return {
        "common": {
            "revenue_yoy": trends.get("revenue_yoy"),
            "net_profit_yoy": trends.get("net_profit_yoy"),
            "profit_minus_revenue_growth": profit_minus_revenue_growth,
            "roe": trends.get("roe"),
            "gross_margin": trends.get("gross_margin"),
            "net_margin": trends.get("net_margin"),
            "debt_to_assets": trends.get("debt_to_assets"),
            "ocf_to_net_profit": trends.get("ocf_to_net_profit"),
            "pe_ttm": _round_or_none(daily_row.get("pe_ttm") or daily_row.get("pe")),
            "pb": _round_or_none(daily_row.get("pb")),
            "ps_ttm": _round_or_none(daily_row.get("ps_ttm") or daily_row.get("ps")),
        },
        "profile_specific": {
            "current_ratio": trends.get("current_ratio"),
            "quick_ratio": trends.get("quick_ratio"),
            "receivables_ratio": trends.get("receivables_ratio"),
            "inventory_ratio": trends.get("inventory_ratio"),
            "roa": trends.get("roa"),
            "grossprofit_margin": _round_or_none(fina_row.get("grossprofit_margin")),
            "netprofit_margin": _round_or_none(fina_row.get("netprofit_margin")),
            "revenue_yoy": trends.get("revenue_yoy"),
            "net_profit_yoy": trends.get("net_profit_yoy"),
        },
    }


def _build_fundamental_compact_signals(
    company_profile: dict[str, Any],
    valuation_snapshot: dict[str, Any],
    financial_snapshot: dict[str, Any],
    statement_summary: dict[str, Any],
) -> dict[str, str]:
    common = financial_snapshot["common"]
    profile_specific = financial_snapshot["profile_specific"]
    company_type = company_profile.get("company_type")

    revenue_yoy = _safe_float(common.get("revenue_yoy"))
    net_profit_yoy = _safe_float(common.get("net_profit_yoy"))
    profit_minus_revenue_growth = _safe_float(common.get("profit_minus_revenue_growth"))
    ocf_to_net_profit = _safe_float(common.get("ocf_to_net_profit"))
    debt_to_assets = _safe_float(common.get("debt_to_assets"))
    current_ratio = _safe_float(profile_specific.get("current_ratio"))
    quick_ratio = _safe_float(profile_specific.get("quick_ratio"))
    pb = _safe_float(common.get("pb"))
    pe_ttm = _safe_float(common.get("pe_ttm"))
    invest_cashflow = _safe_float(statement_summary["cashflow"].get("invest_cashflow"))

    if company_type == "cyclical_resources":
        if net_profit_yoy is not None and revenue_yoy is not None and net_profit_yoy > 30 and profit_minus_revenue_growth is not None and profit_minus_revenue_growth > 20:
            growth_quality = "cyclical_boom"
        elif net_profit_yoy is not None and net_profit_yoy < -15:
            growth_quality = "cyclical_downturn"
        else:
            growth_quality = "cycle_mixed"
    else:
        if revenue_yoy is not None and net_profit_yoy is not None and revenue_yoy > 15 and net_profit_yoy > 15:
            growth_quality = "broad_based_growth"
        elif revenue_yoy is not None and net_profit_yoy is not None and revenue_yoy > 0 and net_profit_yoy > 0:
            growth_quality = "steady_growth"
        elif net_profit_yoy is not None and net_profit_yoy < 0:
            growth_quality = "growth_softening"
        else:
            growth_quality = "mixed_growth"

    if ocf_to_net_profit is not None and ocf_to_net_profit >= 1.0:
        profit_quality = "high_cash_conversion"
    elif ocf_to_net_profit is not None and ocf_to_net_profit >= 0.7:
        profit_quality = "adequate_conversion"
    else:
        profit_quality = "low_conversion"

    if ocf_to_net_profit is not None and ocf_to_net_profit >= 1.0 and invest_cashflow is not None and invest_cashflow < 0:
        cashflow_support = "strong_ocf_high_capex"
    elif ocf_to_net_profit is not None and ocf_to_net_profit >= 1.0:
        cashflow_support = "strong_ocf_support"
    elif ocf_to_net_profit is not None and ocf_to_net_profit >= 0.7:
        cashflow_support = "adequate_ocf_support"
    else:
        cashflow_support = "weak_ocf_support"

    if (debt_to_assets is not None and debt_to_assets >= 65) or (quick_ratio is not None and quick_ratio < 0.7):
        leverage_risk = "elevated_leverage_risk"
    elif (debt_to_assets is not None and debt_to_assets >= 50) or (current_ratio is not None and current_ratio < 1.2):
        leverage_risk = "moderate_liquidity_tight"
    else:
        leverage_risk = "manageable_balance_sheet"

    if company_type == "cyclical_resources":
        if pb is not None and pb >= 4:
            valuation_pressure = "pb_premium_pe_reasonable"
        elif pe_ttm is not None and pe_ttm >= 18:
            valuation_pressure = "earnings_peak_risk"
        else:
            valuation_pressure = "cycle_valuation_balanced"
    else:
        if pe_ttm is not None and pe_ttm >= 35:
            valuation_pressure = "high_multiple_pressure"
        elif pb is not None and pb >= 5:
            valuation_pressure = "high_pb_pressure"
        else:
            valuation_pressure = "valuation_tolerable"

    if company_type == "cyclical_resources":
        cyclical_exposure = "high_sensitivity"
    elif company_type == "financials":
        cyclical_exposure = "policy_rate_sensitive"
    elif company_type == "tmt_growth":
        cyclical_exposure = "innovation_cycle_sensitive"
    else:
        cyclical_exposure = "moderate_sensitivity"

    return {
        "growth_quality": growth_quality,
        "profit_quality": profit_quality,
        "cashflow_support": cashflow_support,
        "leverage_risk": leverage_risk,
        "valuation_pressure": valuation_pressure,
        "cyclical_exposure": cyclical_exposure,
    }


def build_fundamental_data_bundle(ticker: str, analysis_date: str) -> dict[str, Any]:
    ts_code = _normalize_symbol(ticker)
    normalized = normalize_trade_date(analysis_date)
    effective_date = normalized["effective_trade_date"]

    basic_row = _fetch_stock_basic(ts_code)
    company_profile = _detect_company_profile(basic_row.get("industry"))
    report_periods = _resolve_report_periods(company_profile["company_type"])

    daily_basic = _fetch_daily_basic_window(ts_code, effective_date)
    fina_indicator = _query_statement("fina_indicator", ts_code)
    income = _query_statement("income", ts_code)
    balancesheet = _query_statement("balancesheet", ts_code)
    cashflow = _query_statement("cashflow", ts_code)

    daily_row_df = _latest_record_before(daily_basic, effective_date, ["trade_date"])
    fina_row_df = _latest_record_before(fina_indicator, effective_date, ["end_date", "ann_date"])
    income_rows = _records_before(income, effective_date, ["end_date", "ann_date"], limit=report_periods)
    balance_rows = _records_before(balancesheet, effective_date, ["end_date", "ann_date"], limit=report_periods)
    cashflow_rows = _records_before(cashflow, effective_date, ["end_date", "ann_date"], limit=report_periods)

    daily_row = daily_row_df.iloc[0] if not daily_row_df.empty else pd.Series(dtype=object)
    fina_row = fina_row_df.iloc[0] if not fina_row_df.empty else pd.Series(dtype=object)
    latest_income = income_rows.iloc[0] if not income_rows.empty else pd.Series(dtype=object)
    latest_balance = balance_rows.iloc[0] if not balance_rows.empty else pd.Series(dtype=object)
    latest_cashflow = cashflow_rows.iloc[0] if not cashflow_rows.empty else pd.Series(dtype=object)

    trends = _build_financial_trends(fina_row, income_rows, balance_rows, cashflow_rows)

    income_summary = _extract_statement_summary(
        latest_income,
        {
            "revenue": ["revenue", "total_revenue", "total_cogs"],
            "operating_profit": ["operate_profit"],
            "net_profit": ["n_income", "n_income_attr_p", "net_profit"],
            "basic_eps": ["basic_eps"],
            "fin_exp": ["fin_exp"],
            "rd_exp": ["rd_exp"],
        },
    )
    balance_summary = _extract_statement_summary(
        latest_balance,
        {
            "total_assets": ["total_assets"],
            "total_liab": ["total_liab"],
            "money_cap": ["money_cap"],
            "accounts_receiv": ["accounts_receiv"],
            "inventories": ["inventories"],
            "fixed_assets": ["fix_assets", "fixed_assets"],
            "total_hldr_eqy_exc_min_int": ["total_hldr_eqy_exc_min_int"],
        },
    )
    cashflow_summary = _extract_statement_summary(
        latest_cashflow,
        {
            "operate_cashflow": ["n_cashflow_act"],
            "invest_cashflow": ["n_cashflow_inv_act"],
            "finance_cashflow": ["n_cashflow_fin_act"],
            "cash_end_period": ["c_cash_equ_end_period"],
        },
    )

    latest_report_period = None
    for candidate in ("end_date", "ann_date"):
        if candidate in fina_row.index and pd.notna(fina_row.get(candidate)):
            latest_report_period = pd.to_datetime(fina_row.get(candidate)).strftime("%Y-%m-%d")
            break

    valuation_snapshot = {
        "pe_ttm": _round_or_none(daily_row.get("pe_ttm") or daily_row.get("pe")),
        "pb": _round_or_none(daily_row.get("pb")),
        "ps_ttm": _round_or_none(daily_row.get("ps_ttm") or daily_row.get("ps")),
        "dv_ratio": _round_or_none(daily_row.get("dv_ratio")),
        "total_mv": _round_or_none(daily_row.get("total_mv"), 4),
        "circ_mv": _round_or_none(daily_row.get("circ_mv"), 4),
        "turnover_rate": _round_or_none(daily_row.get("turnover_rate")),
    }
    financial_snapshot = _build_financial_snapshot(daily_row, fina_row, trends)
    statement_summary = {
        "income": income_summary,
        "balance_sheet": balance_summary,
        "cashflow": cashflow_summary,
    }

    return {
        "ticker": ts_code,
        "requested_date": normalized["requested_date"],
        "effective_trade_date": effective_date,
        "meta": {
            "name": basic_row.get("name"),
            "industry": basic_row.get("industry"),
            "market": basic_row.get("market"),
            "list_date": basic_row.get("list_date"),
        },
        "company_profile": company_profile,
        "valuation_snapshot": valuation_snapshot,
        "financial_snapshot_raw": {
            "revenue": income_summary.get("revenue"),
            "net_profit": income_summary.get("net_profit"),
            "operating_cashflow": cashflow_summary.get("operate_cashflow"),
            "roe": _round_or_none(fina_row.get("roe")),
            "roa": _round_or_none(fina_row.get("roa")),
            "gross_margin": _round_or_none(fina_row.get("grossprofit_margin")),
            "net_margin": _round_or_none(fina_row.get("netprofit_margin")),
            "debt_to_assets": _round_or_none(fina_row.get("debt_to_assets")),
        },
        "financial_trends": trends,
        "financial_snapshot": financial_snapshot,
        "statement_summary": statement_summary,
        "fundamental_compact_signals": _build_fundamental_compact_signals(
            company_profile=company_profile,
            valuation_snapshot=valuation_snapshot,
            financial_snapshot=financial_snapshot,
            statement_summary=statement_summary,
        ),
        "data_quality": {
            "latest_report_period": latest_report_period,
            "report_periods_used": report_periods,
            "missing_fields": [],
            "source": "tushare",
        },
    }


def get_latest_financial_snapshot(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_fundamental_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "financial_snapshot": bundle["financial_snapshot"],
    }


def get_valuation_snapshot(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_fundamental_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "valuation_snapshot": bundle["valuation_snapshot"],
    }


def get_income_statement_summary(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_fundamental_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "income": bundle["statement_summary"]["income"],
    }


def get_balance_sheet_summary(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_fundamental_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "balance_sheet": bundle["statement_summary"]["balance_sheet"],
    }


def get_cashflow_summary(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_fundamental_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "cashflow": bundle["statement_summary"]["cashflow"],
    }


def get_multi_period_financial_trends(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_fundamental_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "financial_trends": bundle["financial_trends"],
        "company_profile": bundle["company_profile"],
    }
