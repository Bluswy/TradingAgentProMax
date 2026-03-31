from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.company_context_service import (
    build_company_context,
    update_company_context_with_event,
)
from tradingagents.dataflows.event_news_bundle_service import build_event_news_data_bundle
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.tracing import AgentTraceBuilder

from .prompts import EVENT_NEWS_SYSTEM_PROMPT, build_event_news_user_prompt
from .schema import EVENT_NEWS_OUTPUT_TEMPLATE
from .tools import EVENT_NEWS_TOOLS


class EventNewsAgent:
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
        self.tool_map = {tool.name: tool for tool in EVENT_NEWS_TOOLS}

    def analyze(self, ticker: str, analysis_date: str, company_context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.last_trace = None
        trace = AgentTraceBuilder(
            agent_name="EventNewsAgent",
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
                    input_payload={"ticker": ticker, "analysis_date": analysis_date, "date_mode": "natural_day"},
                )
                company_context = build_company_context(
                    ticker=ticker,
                    analysis_date=analysis_date,
                    date_mode="natural_day",
                )
                trace.end_step(
                    step_id,
                    output_payload={
                        "market": company_context.get("identity", {}).get("market"),
                        "exchange": company_context.get("identity", {}).get("exchange"),
                    },
                )

            bundle_step = trace.start_step(
                name="build_event_news_bundle",
                step_type="bundle",
                input_payload={"ticker": ticker, "analysis_date": analysis_date},
            )
            bundle = build_event_news_data_bundle(
                ticker=ticker,
                analysis_date=analysis_date,
                company_context=company_context,
            )
            bundle["company_context"] = company_context
            trace.end_step(
                bundle_step,
                output_payload={
                    "effective_trade_date": bundle.get("effective_trade_date"),
                    "company_news_count": len(bundle.get("company_news", [])),
                    "macro_news_count": len(bundle.get("macro_news", [])),
                    "has_debug_trace": bool(bundle.get("debug_trace")),
                    "has_debug_trace_payload": self.debug and bool(bundle.get("debug_trace")),
                },
            )

            messages = [
                SystemMessage(content=EVENT_NEWS_SYSTEM_PROMPT),
                HumanMessage(content=build_event_news_user_prompt(bundle)),
            ]

            bound_llm = self.llm.bind_tools(EVENT_NEWS_TOOLS)
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
                        "event_state": parsed.get("event_overview", {}).get("state"),
                        "company_events": len(parsed.get("company_specific_events", [])),
                        "industry_events": len(parsed.get("industry_macro_events", [])),
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
                        "company_events": len(parsed.get("company_specific_events", [])),
                        "industry_events": len(parsed.get("industry_macro_events", [])),
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
                                "1. event_overview 必须包含非空 summary；\n"
                                "2. company_specific_events 与 industry_macro_events 至少各1条，且每条必须包含 title、summary、evidence；\n"
                                "3. event_context_snapshot 必须完整返回，且 10 个字段都不能为空；\n"
                                "4. event_chain 必须包含 global_triggers、industry_variables、company_impacts、missing_links 四个数组；\n"
                                "5. 如果证据链不完整，必须把缺失项写进 missing_links；\n"
                                "6. key_catalysts、key_risks、tracking_points 至少各2条；\n"
                                "7. event_summary_zh 必须非空；\n"
                                "8. 不要输出任何解释文字，只输出一个完整JSON对象。"
                            )
                        )
                    )
                    trace.end_step(repair_step, output_payload={"repair_attempted": True})
                    continue

                updated_company_context = update_company_context_with_event(company_context, parsed)
                self.last_trace = trace.finish(
                    output_summary={
                        "effective_trade_date": parsed.get("effective_trade_date"),
                        "event_state": parsed.get("event_overview", {}).get("state"),
                        "company_events": len(parsed.get("company_specific_events", [])),
                        "industry_events": len(parsed.get("industry_macro_events", [])),
                    }
                )
                return {
                    "event_news_data_bundle": bundle,
                    "analysis_result": parsed,
                    "raw_response": response.content,
                    "company_context": updated_company_context,
                    "debug_trace": bundle.get("debug_trace") if self.debug else None,
                    "trace": self.last_trace,
                }

            error = RuntimeError("EventNewsAgent exceeded max 3 iterations without producing a final result.")
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
                raise ValueError(f"EventNewsAgent did not return valid JSON:\n{text}")
            parsed = json.loads(text[start : end + 1])

        normalized = json.loads(json.dumps(EVENT_NEWS_OUTPUT_TEMPLATE, ensure_ascii=False))
        normalized.update(
            {
                "ticker": parsed.get("ticker", normalized["ticker"]),
                "effective_trade_date": parsed.get("effective_trade_date", normalized["effective_trade_date"]),
                "event_compact_signals": bundle.get("event_compact_signals", normalized["event_compact_signals"]),
                "event_context_snapshot": bundle.get("event_context_snapshot", normalized["event_context_snapshot"]),
                "event_chain": bundle.get("event_chain", normalized["event_chain"]),
                "key_catalysts": parsed.get("key_catalysts", normalized["key_catalysts"]),
                "key_risks": parsed.get("key_risks", normalized["key_risks"]),
                "tracking_points": parsed.get("tracking_points", normalized["tracking_points"]),
                "event_summary_zh": parsed.get("event_summary_zh", normalized["event_summary_zh"]),
            }
        )
        if isinstance(parsed.get("event_overview"), dict):
            normalized["event_overview"].update(parsed["event_overview"])
        if isinstance(parsed.get("company_specific_events"), list):
            normalized["company_specific_events"] = parsed["company_specific_events"]
        if isinstance(parsed.get("industry_macro_events"), list):
            normalized["industry_macro_events"] = parsed["industry_macro_events"]
        if isinstance(parsed.get("event_context_snapshot"), dict):
            normalized["event_context_snapshot"].update(
                {
                    "company_event_strength": str(parsed["event_context_snapshot"].get("company_event_strength", normalized["event_context_snapshot"]["company_event_strength"])),
                    "industry_context_strength": str(parsed["event_context_snapshot"].get("industry_context_strength", normalized["event_context_snapshot"]["industry_context_strength"])),
                    "global_context_strength": str(parsed["event_context_snapshot"].get("global_context_strength", normalized["event_context_snapshot"]["global_context_strength"])),
                    "chain_completeness": str(parsed["event_context_snapshot"].get("chain_completeness", normalized["event_context_snapshot"]["chain_completeness"])),
                    "dominant_driver_layer": str(parsed["event_context_snapshot"].get("dominant_driver_layer", normalized["event_context_snapshot"]["dominant_driver_layer"])),
                    "dominant_driver_type": str(parsed["event_context_snapshot"].get("dominant_driver_type", normalized["event_context_snapshot"]["dominant_driver_type"])),
                    "primary_bullish_variable": str(parsed["event_context_snapshot"].get("primary_bullish_variable", normalized["event_context_snapshot"]["primary_bullish_variable"])),
                    "primary_bearish_variable": str(parsed["event_context_snapshot"].get("primary_bearish_variable", normalized["event_context_snapshot"]["primary_bearish_variable"])),
                    "most_actionable_catalyst": str(parsed["event_context_snapshot"].get("most_actionable_catalyst", normalized["event_context_snapshot"]["most_actionable_catalyst"])),
                    "most_critical_risk": str(parsed["event_context_snapshot"].get("most_critical_risk", normalized["event_context_snapshot"]["most_critical_risk"])),
                }
            )
        if isinstance(parsed.get("event_chain"), dict):
            normalized["event_chain"].update(
                {
                    "global_triggers": parsed["event_chain"].get(
                        "global_triggers",
                        normalized["event_chain"]["global_triggers"],
                    ),
                    "industry_variables": parsed["event_chain"].get(
                        "industry_variables",
                        normalized["event_chain"]["industry_variables"],
                    ),
                    "company_impacts": parsed["event_chain"].get(
                        "company_impacts",
                        normalized["event_chain"]["company_impacts"],
                    ),
                    "missing_links": parsed["event_chain"].get(
                        "missing_links",
                        normalized["event_chain"]["missing_links"],
                    ),
                }
            )
        return normalized

    def _is_sparse_output(self, parsed: dict[str, Any]) -> bool:
        overview = parsed.get("event_overview", {})
        if not isinstance(overview, dict) or not str(overview.get("summary", "")).strip():
            return True

        for key in ("company_specific_events", "industry_macro_events"):
            events = parsed.get(key, [])
            if not isinstance(events, list) or len(events) < 1:
                return True
            for event in events:
                if not isinstance(event, dict):
                    return True
                if not str(event.get("title", "")).strip():
                    return True
                if not str(event.get("summary", "")).strip():
                    return True
                if not isinstance(event.get("evidence"), list) or len(event["evidence"]) < 1:
                    return True

        for key in ("key_catalysts", "key_risks", "tracking_points"):
            values = parsed.get(key, [])
            if not isinstance(values, list) or len(values) < 2:
                return True

        snapshot = parsed.get("event_context_snapshot", {})
        if not isinstance(snapshot, dict):
            return True
        for key in (
            "company_event_strength",
            "industry_context_strength",
            "global_context_strength",
            "chain_completeness",
            "dominant_driver_layer",
            "dominant_driver_type",
            "primary_bullish_variable",
            "primary_bearish_variable",
            "most_actionable_catalyst",
            "most_critical_risk",
        ):
            if not str(snapshot.get(key, "")).strip():
                return True

        event_chain = parsed.get("event_chain", {})
        if not isinstance(event_chain, dict):
            return True
        for key in ("global_triggers", "industry_variables", "company_impacts", "missing_links"):
            if key not in event_chain or not isinstance(event_chain.get(key), list):
                return True

        if not str(parsed.get("event_summary_zh", "")).strip():
            return True

        return False
