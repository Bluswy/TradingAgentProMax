from __future__ import annotations

import copy
from typing import Any


COMPANY_CONTEXT_TEMPLATE: dict[str, Any] = {
    "identity": {
        "ticker": "",
        "company_name": "",
        "exchange": "",
        "market": "A_share",
    },
    "analysis_time": {
        "requested_date": "",
        "effective_date": "",
        "date_mode": "",
    },
    "classification": {
        "industry": "",
        "company_type": "",
        "style_tag": "",
        "size_bucket": "",
        "liquidity_bucket": "",
    },
    "business_context": {
        "sub_industry": "",
        "business_model": "",
        "company_intro": "",
        "core_products": [],
        "main_business_items": [],
        "demand_drivers": [],
        "cost_drivers": [],
        "policy_drivers": [],
        "global_risk_drivers": [],
    },
    "market_context": {
        "valuation_style": "",
        "market_attention_points": [],
        "trading_sensitivity": [],
    },
    "technical_context": {
        "trend": {},
        "momentum": {},
        "volatility": {},
        "volume_confirmation": {},
        "relative_strength": {},
        "technical_compact_signals": {},
        "key_levels": {},
        "signals": [],
        "confidence": None,
        "technical_summary_zh": "",
    },
    "fundamental_context": {
        "company_profile": {},
        "growth": {},
        "profitability": {},
        "cashflow_quality": {},
        "balance_sheet_health": {},
        "valuation": {},
        "fundamental_compact_signals": {},
        "financial_snapshot": {},
        "core_risks": [],
        "fundamental_signals": [],
        "confidence": None,
        "fundamental_summary_zh": "",
    },
    "event_context": {
        "event_overview": {},
        "event_compact_signals": {},
        "event_context_snapshot": {},
        "event_chain": {},
        "key_catalysts": [],
        "key_risks": [],
        "tracking_points": [],
        "confidence": None,
        "event_summary_zh": "",
    },
    "search_context": {
        "search_aliases": [],
        "seed_titles": [],
        "ths_member_codes": [],
        "ths_concepts": [],
        "index_memberships": [],
        "preferred_query_style": "keyword_cluster",
        "language_bias": "cn_finance_media",
    },
    "data_quality": {
        "missing_sections": [],
        "stale_sections": [],
        "source_summary": {},
    },
}


def new_company_context() -> dict[str, Any]:
    return copy.deepcopy(COMPANY_CONTEXT_TEMPLATE)


def merge_company_context(base: dict[str, Any] | None, updates: dict[str, Any] | None) -> dict[str, Any]:
    result = new_company_context()

    def _merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
        for key, value in src.items():
            if key not in dst:
                dst[key] = copy.deepcopy(value)
                continue
            if isinstance(dst[key], dict) and isinstance(value, dict):
                _merge(dst[key], value)
            else:
                dst[key] = copy.deepcopy(value)

    if base:
        _merge(result, base)
    if updates:
        _merge(result, updates)
    return result

