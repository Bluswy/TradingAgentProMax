from __future__ import annotations

import json


STRATEGY_DECISION_OUTPUT_TEMPLATE = {
    "ticker": "",
    "effective_date": "",
    "decision": {
        "action": "buy | sell | hold | wait",
        "label_zh": "",
        "confidence": 0.0,
        "summary": "",
    },
    "decision_rationale": {
        "core_reasons": [],
        "supporting_evidence": [],
        "key_conflicts": [],
    },
    "execution_plan": {
        "priority": "high | medium | low",
        "horizon": "short_term | medium_term | long_term",
        "preferred_setup": "",
        "positioning_bias": "aggressive | balanced | conservative",
    },
    "top_supporting_evidence": [
        {
            "module": "technical | fundamental | event_news | sector_flow",
            "title": "",
            "fact": "",
            "importance": 0.0,
        }
    ],
    "top_conflicting_evidence": [
        {
            "module": "technical | fundamental | event_news | sector_flow",
            "title": "",
            "fact": "",
            "importance": 0.0,
        }
    ],
    "module_contributions": {
        "technical": {
            "stance": "supporting | neutral | conflicting",
            "weight": 0.0,
            "summary": "",
        },
        "fundamental": {
            "stance": "supporting | neutral | conflicting",
            "weight": 0.0,
            "summary": "",
        },
        "event_news": {
            "stance": "supporting | neutral | conflicting",
            "weight": 0.0,
            "summary": "",
        },
        "sector_flow": {
            "stance": "supporting | neutral | conflicting",
            "weight": 0.0,
            "summary": "",
        },
    },
    "watchlist": [
        {
            "variable": "",
            "reason": "",
            "window": "",
            "bull_case_if_met": "",
            "bear_case_if_missed": "",
        }
    ],
    "trigger_conditions": [],
    "invalidations": [],
    "invalidations_structured": [
        {
            "type": "price | fundamental | event | flow | valuation",
            "label": "",
            "condition": "",
            "action_after_trigger": "",
            "severity": "high | medium | low",
        }
    ],
    "risk_flags": [],
    "primary_risk": {
        "label": "",
        "category": "technical | fundamental | event | flow | valuation",
        "impact_path": "",
        "risk_level": "high | medium | low",
    },
    "secondary_risks": [
        {
            "label": "",
            "category": "technical | fundamental | event | flow | valuation",
            "impact_path": "",
            "risk_level": "high | medium | low",
        }
    ],
    "decision_summary_zh": "",
}


def get_output_template_json() -> str:
    return json.dumps(STRATEGY_DECISION_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
