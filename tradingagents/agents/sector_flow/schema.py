from __future__ import annotations

import json


SECTOR_FLOW_OUTPUT_TEMPLATE = {
    "ticker": "",
    "effective_trade_date": "",
    "theme_strength": {
        "state": "strong | moderate | weak",
        "summary": "",
        "evidence": [],
    },
    "theme_heat": {
        "state": "hot | warm | cold",
        "summary": "",
        "evidence": [],
    },
    "crowding": {
        "state": "low | medium | high",
        "summary": "",
        "evidence": [],
    },
    "stock_role_in_theme": {
        "state": "leader | core_follower | peripheral | lagging",
        "summary": "",
        "evidence": [],
    },
    "flow_persistence": {
        "state": "persistent | unstable | fading",
        "summary": "",
        "evidence": [],
    },
    "sector_flow_compact_signals": {
        "theme_strength": "",
        "theme_heat": "",
        "crowding_level": "",
        "stock_role": "",
        "flow_persistence": "",
        "rotation_state": "",
    },
    "key_risks": [],
    "tracking_points": [],
    "flow_summary_zh": "",
}


def get_output_template_json() -> str:
    return json.dumps(SECTOR_FLOW_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
