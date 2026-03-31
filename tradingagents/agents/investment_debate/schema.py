from __future__ import annotations

import json


DEBATE_CASE_TEMPLATE = {
    "summary": "",
    "core_points": [],
    "key_evidence": [],
    "confidence": 0.0,
}


DEBATE_JUDGE_TEMPLATE = {
    "debate_focus": {
        "main_conflicts": [],
        "critical_assumptions": [],
        "missing_evidence": [],
    },
    "debate_conclusion": {
        "lean": "bullish | bearish | balanced",
        "summary": "",
        "why": [],
    },
    "debate_summary_zh": "",
}


INVESTMENT_DEBATE_OUTPUT_TEMPLATE = {
    "ticker": "",
    "effective_date": "",
    "bull_case": json.loads(json.dumps(DEBATE_CASE_TEMPLATE, ensure_ascii=False)),
    "bear_case": json.loads(json.dumps(DEBATE_CASE_TEMPLATE, ensure_ascii=False)),
    "debate_focus": {
        "main_conflicts": [],
        "critical_assumptions": [],
        "missing_evidence": [],
    },
    "debate_conclusion": {
        "lean": "bullish | bearish | balanced",
        "summary": "",
        "why": [],
    },
    "debate_summary_zh": "",
}


def get_case_template_json() -> str:
    return json.dumps(DEBATE_CASE_TEMPLATE, ensure_ascii=False, indent=2)


def get_judge_template_json() -> str:
    return json.dumps(DEBATE_JUDGE_TEMPLATE, ensure_ascii=False, indent=2)


def get_output_template_json() -> str:
    return json.dumps(INVESTMENT_DEBATE_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
