from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.company_context_service import (
    build_company_context,
    update_company_context_with_fundamental,
)
from tradingagents.dataflows.fundamental_bundle_service import build_fundamental_data_bundle
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.tracing import AgentTraceBuilder

from ..utils import parse_json_object
from .prompts import FUNDAMENTAL_SYSTEM_PROMPT, build_fundamental_user_prompt
from .schema import FUNDAMENTAL_OUTPUT_TEMPLATE
from .tools import FUNDAMENTAL_TOOLS

FUNDAMENTAL_SUMMARY_ITEM_SPECS = (
    ("growth", "增长"),
    ("profitability", "盈利"),
    ("cashflow_quality", "现金流"),
    ("valuation", "估值"),
)


def _normalize_module_brief(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {"conclusion_zh": "", "rationale_zh": ""}
    return {
        "conclusion_zh": str(value.get("conclusion_zh", "")).strip(),
        "rationale_zh": str(value.get("rationale_zh", "")).strip(),
    }


def _is_valid_module_brief(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    conclusion = str(value.get("conclusion_zh", "")).strip()
    rationale = str(value.get("rationale_zh", "")).strip()
    return 2 <= len(conclusion) <= 8 and 12 <= len(rationale) <= 24


def _normalize_module_summary_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "key": str(item.get("key", "")).strip(),
                "label_zh": str(item.get("label_zh", "")).strip(),
                "conclusion_zh": str(item.get("conclusion_zh", "")).strip(),
                "rationale_zh": str(item.get("rationale_zh", "")).strip(),
            }
        )
    return normalized[: len(FUNDAMENTAL_SUMMARY_ITEM_SPECS)]


def _is_valid_module_summary_items(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != len(FUNDAMENTAL_SUMMARY_ITEM_SPECS):
        return False
    for item, (expected_key, expected_label) in zip(value, FUNDAMENTAL_SUMMARY_ITEM_SPECS, strict=True):
        if not isinstance(item, dict):
            return False
        if str(item.get("key", "")).strip() != expected_key:
            return False
        if str(item.get("label_zh", "")).strip() != expected_label:
            return False
        conclusion = str(item.get("conclusion_zh", "")).strip()
        rationale = str(item.get("rationale_zh", "")).strip()
        if not (2 <= len(conclusion) <= 8 and 12 <= len(rationale) <= 24):
            return False
    return True


class FundamentalAgent:
    def __init__(self, config: dict[str, Any] | None = None, debug: bool = False):
        self.config = config or DEFAULT_CONFIG.copy()
        self.debug = debug
        self.last_trace: dict[str, Any] | None = None
        set_config(self.config)

        llm_kwargs: dict[str, Any] = {}
        if self.config.get("llm_provider") == "openai" and self.config.get("openai_reasoning_effort"):
            llm_kwargs["reasoning_effort"] = self.config.get("openai_reasoning_effort")
        if self.config.get("llm_provider") == "google" and self.config.get("google_thinking_level"):
            llm_kwargs["thinking_level"] = self.config.get("google_thinking_level")
        llm_kwargs["project_dir"] = self.config.get("project_dir")
        if self.config.get("llm_provider") in ("bailian", "dashscope") and self.config.get("bailian_api_key"):
            llm_kwargs["api_key"] = self.config.get("bailian_api_key")
        if self.config.get("llm_provider") in ("bailian", "dashscope"):
            llm_kwargs["bailian_enable_thinking"] = self.config.get("bailian_enable_thinking")
            if self.config.get("bailian_thinking_budget") is not None:
                llm_kwargs["bailian_thinking_budget"] = self.config.get("bailian_thinking_budget")

        llm_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config.get("deep_think_llm", "qwen3.5-plus"),
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        self.llm = llm_client.get_llm()
        self.tool_map = {tool.name: tool for tool in FUNDAMENTAL_TOOLS}

    def analyze(self, ticker: str, analysis_date: str, company_context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.last_trace = None
        trace = AgentTraceBuilder(
            agent_name="FundamentalAgent",
            agent_type="agent",
            config=self.config,
            input_summary={
                "ticker": ticker,
                "analysis_date": analysis_date,
                "has_company_context": company_context is not None,
            },
        )
        try:
            if company_context is None:
                step_id = trace.start_step(
                    name="build_company_context",
                    step_type="context",
                    input_payload={"ticker": ticker, "analysis_date": analysis_date, "date_mode": "trade_day"},
                )
                company_context = build_company_context(
                    ticker=ticker,
                    analysis_date=analysis_date,
                    date_mode="trade_day",
                )
                trace.end_step(
                    step_id,
                    output_payload={
                        "market": company_context.get("identity", {}).get("market"),
                        "exchange": company_context.get("identity", {}).get("exchange"),
                    },
                )

            bundle_step = trace.start_step(
                name="build_fundamental_bundle",
                step_type="bundle",
                input_payload={"ticker": ticker, "analysis_date": analysis_date},
            )
            bundle = build_fundamental_data_bundle(
                ticker=ticker,
                analysis_date=analysis_date,
                company_context=company_context,
            )
            bundle["company_context"] = company_context
            trace.end_step(
                bundle_step,
                output_payload={
                    "effective_trade_date": bundle.get("effective_trade_date"),
                    "company_type": bundle.get("company_profile", {}).get("company_type"),
                    "report_periods_used": bundle.get("data_quality", {}).get("report_periods_used"),
                },
            )

            messages = [
                SystemMessage(content=FUNDAMENTAL_SYSTEM_PROMPT),
                HumanMessage(content=build_fundamental_user_prompt(bundle)),
            ]

            bound_llm = self.llm.bind_tools(FUNDAMENTAL_TOOLS)
            repair_attempted = False
            for round_idx in range(3):
                llm_step = trace.start_step(
                    name=f"llm_invoke_round_{round_idx + 1}",
                    step_type="llm",
                    input_payload={"round": round_idx + 1, "message_count": len(messages)},
                )
                response = bound_llm.invoke(messages)
                messages.append(response)
                trace.end_step(
                    llm_step,
                    output_payload={
                        "has_tool_calls": bool(getattr(response, "tool_calls", None)),
                        "content_preview": str(response.content)[:500],
                    },
                )

                if getattr(response, "tool_calls", None):
                    for tool_call in response.tool_calls:
                        tool_step = trace.start_step(
                            name=f"tool_call_{tool_call['name']}",
                            step_type="tool_call",
                            input_payload={"tool_name": tool_call["name"], "args": tool_call["args"]},
                        )
                        tool = self.tool_map[tool_call["name"]]
                        tool_result = tool.invoke(tool_call["args"])
                        messages.append(ToolMessage(content=tool_result, tool_call_id=tool_call["id"]))
                        trace.end_step(tool_step, output_payload={"result_preview": str(tool_result)[:800]})
                    continue

                parse_step = trace.start_step(
                    name="parse_json_response",
                    step_type="parse",
                    input_payload={"content_preview": str(response.content)[:500]},
                )
                parsed = self._parse_json_response(response.content, bundle)
                trace.end_step(
                    parse_step,
                    output_payload={
                        "growth": parsed.get("growth", {}).get("state"),
                        "valuation": parsed.get("valuation", {}).get("state"),
                        "confidence": parsed.get("confidence"),
                    },
                )

                quality_step = trace.start_step(
                    name="quality_gate",
                    step_type="quality_gate",
                    input_payload={"round": round_idx + 1},
                )
                is_sparse = self._is_sparse_output(parsed)
                trace.end_step(
                    quality_step,
                    output_payload={"is_sparse": is_sparse},
                    metrics={
                        "core_risks_count": len(parsed.get("core_risks", [])),
                        "signals_count": len(parsed.get("fundamental_signals", [])),
                    },
                )
                if is_sparse and not repair_attempted:
                    repair_attempted = True
                    repair_step = trace.start_step(
                        name="repair_prompt",
                        step_type="repair",
                        input_payload={"reason": "sparse_output"},
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                "你的上一版JSON过于稀疏，未满足输出要求。请重新输出完整JSON，并遵守以下硬性约束：\n"
                                "1. growth、profitability、cashflow_quality、balance_sheet_health、valuation 都必须包含非空 summary；\n"
                                "2. 上述各部分都必须包含至少2条 evidence；\n"
                                "3. core_risks 至少2条；\n"
                                "4. fundamental_compact_signals 的6个字段都必须填写非空短标签；\n"
                                "5. fundamental_signals 至少2条，每条都必须有 description 和 evidence；\n"
                                "6. financial_snapshot.common 至少8个非空字段；\n"
                                "7. module_summary_items 必须按固定顺序返回4条：growth/增长、profitability/盈利、cashflow_quality/现金流、valuation/估值；\n"
                                "8. 每条都必须有 conclusion_zh(2-8字) 和 rationale_zh(12-24字)；\n"
                                "9. 不要输出任何解释文字，只输出一个完整JSON对象。"
                            )
                        )
                    )
                    trace.end_step(repair_step, output_payload={"repair_attempted": True})
                    continue

                updated_company_context = update_company_context_with_fundamental(company_context, parsed)
                self.last_trace = trace.finish(
                    output_summary={
                        "effective_trade_date": parsed.get("effective_trade_date"),
                        "growth": parsed.get("growth", {}).get("state"),
                        "valuation": parsed.get("valuation", {}).get("state"),
                        "company_type": parsed.get("company_profile", {}).get("company_type"),
                        "confidence": parsed.get("confidence"),
                    }
                )
                return {
                    "fundamental_data_bundle": bundle,
                    "analysis_result": parsed,
                    "raw_response": response.content,
                    "company_context": updated_company_context,
                    "trace": self.last_trace,
                }

            error = RuntimeError("FundamentalAgent exceeded max 3 iterations without producing a final result.")
            self.last_trace = trace.finish(error=error)
            raise error
        except Exception as error:
            if self.last_trace is None or self.last_trace.get("status") == "running":
                self.last_trace = trace.finish(error=error)
            raise

    def _parse_json_response(self, content: str, bundle: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_json_object(content, source="FundamentalAgent output")

        normalized = json.loads(json.dumps(FUNDAMENTAL_OUTPUT_TEMPLATE, ensure_ascii=False))
        bundle_company_profile = bundle.get("company_profile", {})
        bundle_financial_snapshot = bundle.get("financial_snapshot", {})
        normalized.update(
            {
                "ticker": parsed.get("ticker", normalized["ticker"]),
                "effective_trade_date": parsed.get("effective_trade_date", normalized["effective_trade_date"]),
                "company_profile": bundle_company_profile or parsed.get("company_profile", normalized["company_profile"]),
                "core_risks": parsed.get("core_risks", normalized["core_risks"]),
                "fundamental_compact_signals": bundle.get(
                    "fundamental_compact_signals", normalized["fundamental_compact_signals"]
                ),
                "fundamental_signals": parsed.get("fundamental_signals", normalized["fundamental_signals"]),
                "confidence": parsed.get("confidence", normalized["confidence"]),
                "module_brief": _normalize_module_brief(parsed.get("module_brief")),
                "module_summary_items": _normalize_module_summary_items(parsed.get("module_summary_items")),
                "fundamental_summary_zh": parsed.get("fundamental_summary_zh", normalized["fundamental_summary_zh"]),
            }
        )
        for section in ("growth", "profitability", "cashflow_quality", "balance_sheet_health", "valuation"):
            if isinstance(parsed.get(section), dict):
                normalized[section].update(parsed[section])

        if isinstance(bundle_financial_snapshot, dict):
            if isinstance(bundle_financial_snapshot.get("common"), dict):
                normalized["financial_snapshot"]["common"].update(bundle_financial_snapshot["common"])
            if isinstance(bundle_financial_snapshot.get("profile_specific"), dict):
                normalized["financial_snapshot"]["profile_specific"].update(bundle_financial_snapshot["profile_specific"])

        if isinstance(parsed.get("financial_snapshot"), dict):
            if isinstance(parsed["financial_snapshot"].get("common"), dict):
                normalized["financial_snapshot"]["common"].update(parsed["financial_snapshot"]["common"])
            if isinstance(parsed["financial_snapshot"].get("profile_specific"), dict):
                normalized["financial_snapshot"]["profile_specific"].update(parsed["financial_snapshot"]["profile_specific"])

        return normalized

    def _is_sparse_output(self, parsed: dict[str, Any]) -> bool:
        for section in ("growth", "profitability", "cashflow_quality", "balance_sheet_health", "valuation"):
            value = parsed.get(section, {})
            if not isinstance(value, dict):
                return True
            if not str(value.get("summary", "")).strip():
                return True
            if not isinstance(value.get("evidence"), list) or len(value["evidence"]) < 2:
                return True

        snapshot = parsed.get("financial_snapshot", {})
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("common"), dict):
            return True
        filled_common = sum(1 for value in snapshot["common"].values() if value is not None)
        if filled_common < 8:
            return True

        compact_signals = parsed.get("fundamental_compact_signals", {})
        if not isinstance(compact_signals, dict):
            return True
        for key in FUNDAMENTAL_OUTPUT_TEMPLATE["fundamental_compact_signals"].keys():
            if not str(compact_signals.get(key, "")).strip():
                return True

        core_risks = parsed.get("core_risks", [])
        if not isinstance(core_risks, list) or len(core_risks) < 2:
            return True

        signals = parsed.get("fundamental_signals", [])
        if not isinstance(signals, list) or len(signals) < 2:
            return True
        for signal in signals:
            if not isinstance(signal, dict):
                return True
            if not str(signal.get("description", "")).strip():
                return True
            if not isinstance(signal.get("evidence"), list) or len(signal["evidence"]) < 1:
                return True

        if not str(parsed.get("fundamental_summary_zh", "")).strip():
            return True
        if not _is_valid_module_brief(parsed.get("module_brief")):
            return True
        if not _is_valid_module_summary_items(parsed.get("module_summary_items")):
            return True

        return False
