from __future__ import annotations

import json


STRATEGY_STYLE_OUTPUT_TEMPLATE = {
    "ticker": "",
    "effective_date": "",
    "primary_strategy": {
        "type": "pb_roe_investing | macro_cycle_investing | prosperity_investing | tech_revolution_investing | pvp_trading",
        "label_zh": "",
        "summary": "",
        "confidence": 0.0,
    },
    "secondary_strategies": [],
    "strategy_rationale": {
        "why_this_strategy": [],
        "why_not_others": [],
    },
    "decision_priority_variables": [],
    "decision_kpis": [],
    "strategy_constraints": [],
    "holding_horizon": {
        "type": "short_term | medium_term | long_term",
        "summary": "",
    },
    "invalidations": [],
    "strategy_routing": {
        "technical_weight": "high | medium | low",
        "fundamental_weight": "high | medium | low",
        "event_weight": "high | medium | low",
        "sector_flow_weight": "high | medium | low",
    },
    "strategy_summary_zh": "",
}


def get_output_template_json() -> str:
    return json.dumps(STRATEGY_STYLE_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
