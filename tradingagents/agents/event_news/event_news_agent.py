from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.event_news_bundle_service import build_event_news_data_bundle
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

from .prompts import EVENT_NEWS_SYSTEM_PROMPT, build_event_news_user_prompt
from .schema import EVENT_NEWS_OUTPUT_TEMPLATE
from .tools import EVENT_NEWS_TOOLS


class EventNewsAgent:
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
        self.tool_map = {tool.name: tool for tool in EVENT_NEWS_TOOLS}

    def analyze(self, ticker: str, analysis_date: str) -> dict[str, Any]:
        bundle = build_event_news_data_bundle(ticker=ticker, analysis_date=analysis_date)
        messages = [
            SystemMessage(content=EVENT_NEWS_SYSTEM_PROMPT),
            HumanMessage(content=build_event_news_user_prompt(bundle)),
        ]

        bound_llm = self.llm.bind_tools(EVENT_NEWS_TOOLS)
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
                            "1. event_overview 必须包含非空 summary；\n"
                            "2. company_specific_events 与 industry_macro_events 至少各1条，且每条必须包含 title、summary、evidence；\n"
                            "3. key_catalysts、key_risks、tracking_points 至少各2条；\n"
                            "4. event_summary_zh 必须非空；\n"
                            "5. 不要输出任何解释文字，只输出一个完整JSON对象。"
                        )
                    )
                )
                continue

            return {
                "event_news_data_bundle": bundle,
                "analysis_result": parsed,
                "raw_response": response.content,
                "debug_trace": bundle.get("debug_trace") if self.debug else None,
            }

        raise RuntimeError("EventNewsAgent exceeded max 3 iterations without producing a final result.")

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

        if not str(parsed.get("event_summary_zh", "")).strip():
            return True

        return False
