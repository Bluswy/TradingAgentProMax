from __future__ import annotations

import json


COMPANY_ANALYSIS_REPORT_OUTPUT_TEMPLATE = {
    "ticker": "",
    "effective_date": "",
    "report_title": "",
    "executive_summary": [],
    "key_takeaways": [],
    "report_markdown": "",
}


def get_output_template_json() -> str:
    return json.dumps(COMPANY_ANALYSIS_REPORT_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
