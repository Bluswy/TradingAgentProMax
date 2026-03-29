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
    "key_catalysts": [],
    "key_risks": [],
    "tracking_points": [],
    "event_summary_zh": "",
}


def get_output_template_json() -> str:
    return json.dumps(EVENT_NEWS_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
