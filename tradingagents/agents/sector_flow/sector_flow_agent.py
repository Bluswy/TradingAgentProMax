from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.sector_flow_bundle_service import build_sector_flow_data_bundle
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.tracing import AgentTraceBuilder

from .prompts import SECTOR_FLOW_SYSTEM_PROMPT, build_sector_flow_user_prompt
from .schema import SECTOR_FLOW_OUTPUT_TEMPLATE
from .tools import SECTOR_FLOW_TOOLS


class SectorFlowAgent:
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
        self.tool_map = {tool.name: tool for tool in SECTOR_FLOW_TOOLS}

    def analyze(self, ticker: str, analysis_date: str) -> dict[str, Any]:
        self.last_trace = None
        trace = AgentTraceBuilder(
            agent_name="SectorFlowAgent",
            agent_type="agent",
            config=self.config,
            input_summary={"ticker": ticker, "analysis_date": analysis_date},
        )
        try:
            bundle_step = trace.start_step(
                name="build_sector_flow_bundle",
                step_type="bundle",
                input_payload={"ticker": ticker, "analysis_date": analysis_date},
            )
            bundle = build_sector_flow_data_bundle(ticker=ticker, analysis_date=analysis_date)
            trace.end_step(
                bundle_step,
                output_payload={
                    "effective_trade_date": bundle.get("effective_trade_date"),
                    "sector_name": bundle.get("meta", {}).get("sector_name"),
                    "sector_member_count": bundle.get("meta", {}).get("sector_member_count"),
                },
            )
            messages = [
                SystemMessage(content=SECTOR_FLOW_SYSTEM_PROMPT),
                HumanMessage(content=build_sector_flow_user_prompt(bundle)),
            ]

            bound_llm = self.llm.bind_tools(SECTOR_FLOW_TOOLS)
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
                        "theme_strength": parsed.get("theme_strength", {}).get("state"),
                        "theme_heat": parsed.get("theme_heat", {}).get("state"),
                        "stock_role": parsed.get("stock_role_in_theme", {}).get("state"),
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
                    metrics={"key_risks_count": len(parsed.get("key_risks", []))},
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
                                "1. theme_strength、theme_heat、crowding、stock_role_in_theme、flow_persistence 都必须包含非空 summary；\n"
                                "2. 上述各部分都必须包含至少2条 evidence；\n"
                                "3. sector_flow_compact_signals 的6个字段都必须填写非空短标签；\n"
                                "4. key_risks 和 tracking_points 至少各2条；\n"
                                "5. flow_summary_zh 必须非空；\n"
                                "6. 不要输出任何解释文字，只输出一个完整JSON对象。"
                            )
                        )
                    )
                    trace.end_step(repair_step, output_payload={"repair_attempted": True})
                    continue

                self.last_trace = trace.finish(
                    output_summary={
                        "effective_trade_date": parsed.get("effective_trade_date"),
                        "theme_strength": parsed.get("theme_strength", {}).get("state"),
                        "theme_heat": parsed.get("theme_heat", {}).get("state"),
                        "stock_role": parsed.get("stock_role_in_theme", {}).get("state"),
                    }
                )
                return {
                    "sector_flow_data_bundle": bundle,
                    "analysis_result": parsed,
                    "raw_response": response.content,
                    "trace": self.last_trace,
                }

            error = RuntimeError("SectorFlowAgent exceeded max 3 iterations without producing a final result.")
            self.last_trace = trace.finish(error=error)
            raise error
        except Exception as error:
            if self.last_trace is None or self.last_trace.get("status") == "running":
                self.last_trace = trace.finish(error=error)
            raise

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
                raise ValueError(f"SectorFlowAgent did not return valid JSON:\n{text}")
            parsed = json.loads(text[start : end + 1])

        normalized = json.loads(json.dumps(SECTOR_FLOW_OUTPUT_TEMPLATE, ensure_ascii=False))
        normalized.update(
            {
                "ticker": parsed.get("ticker", normalized["ticker"]),
                "effective_trade_date": parsed.get("effective_trade_date", normalized["effective_trade_date"]),
                "sector_flow_compact_signals": bundle.get(
                    "sector_flow_compact_signals",
                    normalized["sector_flow_compact_signals"],
                ),
                "key_risks": parsed.get("key_risks", normalized["key_risks"]),
                "tracking_points": parsed.get("tracking_points", normalized["tracking_points"]),
                "flow_summary_zh": parsed.get("flow_summary_zh", normalized["flow_summary_zh"]),
            }
        )
        for section in ("theme_strength", "theme_heat", "crowding", "stock_role_in_theme", "flow_persistence"):
            if isinstance(parsed.get(section), dict):
                normalized[section].update(parsed[section])
        if isinstance(parsed.get("sector_flow_compact_signals"), dict):
            normalized["sector_flow_compact_signals"].update(parsed["sector_flow_compact_signals"])
        return normalized

    def _is_sparse_output(self, parsed: dict[str, Any]) -> bool:
        for section in ("theme_strength", "theme_heat", "crowding", "stock_role_in_theme", "flow_persistence"):
            value = parsed.get(section, {})
            if not isinstance(value, dict):
                return True
            if not str(value.get("summary", "")).strip():
                return True
            if not isinstance(value.get("evidence"), list) or len(value["evidence"]) < 2:
                return True

        compact_signals = parsed.get("sector_flow_compact_signals", {})
        if not isinstance(compact_signals, dict):
            return True
        for key in SECTOR_FLOW_OUTPUT_TEMPLATE["sector_flow_compact_signals"].keys():
            if not str(compact_signals.get(key, "")).strip():
                return True

        for key in ("key_risks", "tracking_points"):
            values = parsed.get(key, [])
            if not isinstance(values, list) or len(values) < 2:
                return True

        if not str(parsed.get("flow_summary_zh", "")).strip():
            return True

        return False
