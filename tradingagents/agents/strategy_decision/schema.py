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
    "trigger_conditions": [],
    "invalidations": [],
    "risk_flags": [],
    "decision_summary_zh": "",
}


def get_output_template_json() -> str:
    return json.dumps(STRATEGY_DECISION_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
