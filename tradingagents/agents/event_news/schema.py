from __future__ import annotations

import json


EVENT_NEWS_OUTPUT_TEMPLATE = {
    "ticker": "",
    "effective_trade_date": "",
    "event_overview": {
        "state": "catalyst_positive | catalyst_negative | mixed | quiet",
        "summary": "",
        "confidence": 0.0,
    },
    "company_specific_events": [
        {
            "event_type": "earnings | order | product | mna | buyback | reduction | litigation | regulation | capacity | other",
            "title": "",
            "direction": "bullish | bearish | neutral",
            "importance": 0.0,
            "time_horizon": "short_term | medium_term | long_term",
            "affected_variables": [],
            "evidence": [],
            "summary": "",
        }
    ],
    "industry_macro_events": [
        {
            "event_type": "policy | industry_cycle | commodity | liquidity | geopolitics | regulation | other",
            "title": "",
            "direction": "bullish | bearish | neutral",
            "importance": 0.0,
            "time_horizon": "short_term | medium_term | long_term",
            "affected_variables": [],
            "evidence": [],
            "summary": "",
        }
    ],
    "event_compact_signals": {
        "company_event_bias": "",
        "macro_event_bias": "",
        "event_density": "",
        "policy_sensitivity": "",
        "earnings_catalyst_state": "",
        "risk_event_level": "",
    },
    "event_context_snapshot": {
        "company_event_strength": "",
        "industry_context_strength": "",
        "global_context_strength": "",
        "chain_completeness": "",
        "dominant_driver_layer": "",
        "dominant_driver_type": "",
        "primary_bullish_variable": "",
        "primary_bearish_variable": "",
        "most_actionable_catalyst": "",
        "most_critical_risk": "",
    },
    "event_chain": {
        "global_triggers": [],
        "industry_variables": [],
        "company_impacts": [],
        "missing_links": [],
    },
    "key_catalysts": [],
    "key_risks": [],
    "tracking_points": [],
    "module_brief": {
        "conclusion_zh": "",
        "rationale_zh": "",
    },
    "module_summary_items": [
        {
            "key": "event_bias",
            "label_zh": "事件倾向",
            "conclusion_zh": "",
            "rationale_zh": "",
        },
        {
            "key": "core_catalyst",
            "label_zh": "核心催化",
            "conclusion_zh": "",
            "rationale_zh": "",
        },
        {
            "key": "bullish_factor",
            "label_zh": "利好",
            "conclusion_zh": "",
            "rationale_zh": "",
        },
        {
            "key": "bearish_factor",
            "label_zh": "利空",
            "conclusion_zh": "",
            "rationale_zh": "",
        },
    ],
    "event_summary_zh": "",
}


def get_output_template_json() -> str:
    return json.dumps(EVENT_NEWS_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
