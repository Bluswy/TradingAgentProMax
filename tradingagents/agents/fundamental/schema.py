from __future__ import annotations

import json


FUNDAMENTAL_OUTPUT_TEMPLATE = {
    "ticker": "",
    "effective_trade_date": "",
    "company_profile": {
        "company_type": "",
        "industry": "",
        "analysis_focus": [],
        "deprioritized_metrics": [],
    },
    "growth": {
        "state": "improving | weakening | stable",
        "strength": 0.0,
        "summary": "",
        "evidence": [],
    },
    "profitability": {
        "state": "strong | average | weak",
        "summary": "",
        "evidence": [],
    },
    "cashflow_quality": {
        "state": "strong | average | weak",
        "summary": "",
        "evidence": [],
    },
    "balance_sheet_health": {
        "state": "healthy | moderate | weak",
        "summary": "",
        "evidence": [],
    },
    "valuation": {
        "state": "cheap | fair | expensive",
        "summary": "",
        "evidence": [],
    },
    "core_risks": [],
    "fundamental_compact_signals": {
        "growth_quality": "",
        "profit_quality": "",
        "cashflow_support": "",
        "leverage_risk": "",
        "valuation_pressure": "",
        "cyclical_exposure": "",
    },
    "fundamental_signals": [
        {
            "type": "growth | quality | valuation | risk",
            "direction": "bullish | bearish | neutral",
            "strength": 0.0,
            "description": "",
            "evidence": [],
        }
    ],
    "financial_snapshot": {
        "common": {
            "revenue_yoy": None,
            "net_profit_yoy": None,
            "roe": None,
            "gross_margin": None,
            "net_margin": None,
            "debt_to_assets": None,
            "ocf_to_net_profit": None,
            "pe_ttm": None,
            "pb": None,
            "ps_ttm": None,
        },
        "profile_specific": {},
    },
    "confidence": 0.0,
    "fundamental_summary_zh": "",
}


def get_output_template_json() -> str:
    return json.dumps(FUNDAMENTAL_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
