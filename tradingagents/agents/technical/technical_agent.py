from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.company_context_service import (
    build_company_context,
    update_company_context_with_technical,
)
from tradingagents.dataflows.technical_bundle_service import build_technical_data_bundle
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.tracing import AgentTraceBuilder

from .prompts import TECHNICAL_SYSTEM_PROMPT, build_technical_user_prompt
from .schema import TECHNICAL_OUTPUT_TEMPLATE
from .tools import TECHNICAL_TOOLS


class TechnicalAgent:
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
        self.tool_map = {tool.name: tool for tool in TECHNICAL_TOOLS}

    def analyze(self, ticker: str, analysis_date: str, company_context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.last_trace = None
        trace = AgentTraceBuilder(
            agent_name="TechnicalAgent",
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

            step_id = trace.start_step(
                name="build_technical_bundle",
                step_type="bundle",
                input_payload={"ticker": ticker, "analysis_date": analysis_date, "lookback_trading_days": 90},
            )
            bundle = build_technical_data_bundle(
                ticker=ticker,
                analysis_date=analysis_date,
                lookback_trading_days=90,
                company_context=company_context,
            )
            bundle["company_context"] = company_context
            trace.end_step(
                step_id,
                output_payload={
                    "effective_trade_date": bundle.get("effective_trade_date"),
                    "indicator_snapshot_keys": len((bundle.get("indicator_snapshot") or {}).keys()),
                    "signal_count": len(bundle.get("signals") or []),
                },
            )

            messages = [
                SystemMessage(content=TECHNICAL_SYSTEM_PROMPT),
                HumanMessage(content=build_technical_user_prompt(bundle)),
            ]

            bound_llm = self.llm.bind_tools(TECHNICAL_TOOLS)
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
                        messages.append(
                            ToolMessage(
                                content=tool_result,
                                tool_call_id=tool_call["id"],
                            )
                        )
                        trace.end_step(
                            tool_step,
                            output_payload={"result_preview": str(tool_result)[:800]},
                        )
                    continue

                parse_step = trace.start_step(
                    name="parse_json_response",
                    step_type="parse",
                    input_payload={"content_preview": str(response.content)[:500]},
                )
                parsed = self._parse_json_response(response.content)
                trace.end_step(
                    parse_step,
                    output_payload={
                        "trend": parsed.get("trend", {}).get("short_term"),
                        "momentum": parsed.get("momentum", {}).get("state"),
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
                    metrics={"signal_count": len(parsed.get("signals", []))},
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
                                "1. trend、momentum、volatility、volume_confirmation、relative_strength 都必须包含非空 summary；\n"
                                "2. 上述各部分都必须包含至少2条 evidence；\n"
                                "3. indicator_snapshot 必须填写足够多的关键数值字段，至少10个非空字段；\n"
                                "4. signals 至少2条，每条都必须有 description 和 evidence；\n"
                                "5. 不要输出任何解释文字，只输出一个完整JSON对象。"
                            )
                        )
                    )
                    trace.end_step(repair_step, output_payload={"repair_attempted": True})
                    continue
                updated_company_context = update_company_context_with_technical(company_context, parsed)
                self.last_trace = trace.finish(
                    output_summary={
                        "effective_trade_date": parsed.get("effective_trade_date"),
                        "trend": parsed.get("trend", {}).get("short_term"),
                        "momentum": parsed.get("momentum", {}).get("state"),
                        "confidence": parsed.get("confidence"),
                    }
                )
                return {
                    "technical_data_bundle": bundle,
                    "analysis_result": parsed,
                    "raw_response": response.content,
                    "company_context": updated_company_context,
                    "trace": self.last_trace,
                }

            error = RuntimeError("TechnicalAgent exceeded max 3 iterations without producing a final result.")
            self.last_trace = trace.finish(error=error)
            raise error
        except Exception as error:
            if self.last_trace is None or self.last_trace.get("status") == "running":
                self.last_trace = trace.finish(error=error)
            raise

    def _parse_json_response(self, content: str) -> dict[str, Any]:
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
                raise ValueError(f"TechnicalAgent did not return valid JSON:\n{text}")
            parsed = json.loads(text[start : end + 1])

        normalized = json.loads(json.dumps(TECHNICAL_OUTPUT_TEMPLATE, ensure_ascii=False))
        normalized.update(
            {
                "ticker": parsed.get("ticker", normalized["ticker"]),
                "effective_trade_date": parsed.get("effective_trade_date", normalized["effective_trade_date"]),
                "confidence": parsed.get("confidence", normalized["confidence"]),
                "risk_flags": parsed.get("risk_flags", normalized["risk_flags"]),
                "invalidations": parsed.get("invalidations", normalized["invalidations"]),
                "signals": parsed.get("signals", normalized["signals"]),
                "technical_summary_zh": parsed.get(
                    "technical_summary_zh", normalized["technical_summary_zh"]
                ),
            }
        )
        for section in (
            "trend",
            "momentum",
            "volatility",
            "volume_confirmation",
            "relative_strength",
            "key_levels",
        ):
            if isinstance(parsed.get(section), dict):
                normalized[section].update(parsed[section])
        if isinstance(parsed.get("indicator_snapshot"), dict):
            normalized["indicator_snapshot"].update(parsed["indicator_snapshot"])
        return normalized

    def _is_sparse_output(self, parsed: dict[str, Any]) -> bool:
        required_sections = (
            "trend",
            "momentum",
            "volatility",
            "volume_confirmation",
            "relative_strength",
        )
        for section in required_sections:
            value = parsed.get(section, {})
            if not isinstance(value, dict):
                return True
            if not str(value.get("summary", "")).strip():
                return True
            evidence = value.get("evidence", [])
            if section in ("trend", "relative_strength") and not isinstance(evidence, list):
                return True
            if isinstance(evidence, list) and len(evidence) < 2:
                return True

        indicator_snapshot = parsed.get("indicator_snapshot", {})
        if not isinstance(indicator_snapshot, dict):
            return True

        filled_snapshot_fields = sum(
            1
            for key in TECHNICAL_OUTPUT_TEMPLATE["indicator_snapshot"].keys()
            if indicator_snapshot.get(key) is not None
        )
        if filled_snapshot_fields < 10:
            return True

        signals = parsed.get("signals", [])
        if not isinstance(signals, list) or len(signals) < 2:
            return True
        for signal in signals:
            if not isinstance(signal, dict):
                return True
            if not str(signal.get("description", "")).strip():
                return True
            if not isinstance(signal.get("evidence"), list) or len(signal["evidence"]) < 1:
                return True

        if not str(parsed.get("technical_summary_zh", "")).strip():
            return True

        return False
