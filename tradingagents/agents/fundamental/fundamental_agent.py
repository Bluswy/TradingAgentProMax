from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.fundamental_bundle_service import build_fundamental_data_bundle
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

from .prompts import FUNDAMENTAL_SYSTEM_PROMPT, build_fundamental_user_prompt
from .schema import FUNDAMENTAL_OUTPUT_TEMPLATE
from .tools import FUNDAMENTAL_TOOLS


class FundamentalAgent:
    def __init__(self, config: dict[str, Any] | None = None, debug: bool = False):
        self.config = config or DEFAULT_CONFIG.copy()
        self.debug = debug
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

    def analyze(self, ticker: str, analysis_date: str) -> dict[str, Any]:
        bundle = build_fundamental_data_bundle(ticker=ticker, analysis_date=analysis_date)
        messages = [
            SystemMessage(content=FUNDAMENTAL_SYSTEM_PROMPT),
            HumanMessage(content=build_fundamental_user_prompt(bundle)),
        ]

        bound_llm = self.llm.bind_tools(FUNDAMENTAL_TOOLS)
        repair_attempted = False
        for _ in range(3):
            response = bound_llm.invoke(messages)
            messages.append(response)

            if getattr(response, "tool_calls", None):
                for tool_call in response.tool_calls:
                    tool = self.tool_map[tool_call["name"]]
                    tool_result = tool.invoke(tool_call["args"])
                    messages.append(ToolMessage(content=tool_result, tool_call_id=tool_call["id"]))
                continue

            parsed = self._parse_json_response(response.content, bundle)
            if self._is_sparse_output(parsed) and not repair_attempted:
                repair_attempted = True
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
                            "7. 不要输出任何解释文字，只输出一个完整JSON对象。"
                        )
                    )
                )
                continue

            return {
                "fundamental_data_bundle": bundle,
                "analysis_result": parsed,
                "raw_response": response.content,
            }

        raise RuntimeError("FundamentalAgent exceeded max 3 iterations without producing a final result.")

    def _parse_json_response(self, content: str, bundle: dict[str, Any]) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError(f"FundamentalAgent did not return valid JSON:\n{text}")
            parsed = json.loads(text[start : end + 1])

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

        return False
