from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.tracing import AgentTraceBuilder

from .prompts import (
    STRATEGY_DECISION_SYSTEM_PROMPT,
    build_strategy_decision_context_payload,
    build_strategy_decision_user_prompt,
)
from .schema import STRATEGY_DECISION_OUTPUT_TEMPLATE


VALID_ACTIONS = {"buy", "sell", "hold", "wait"}
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_HORIZONS = {"short_term", "medium_term", "long_term"}
VALID_POSITIONING = {"aggressive", "balanced", "conservative"}
ACTION_LABELS = {
    "buy": "买入",
    "sell": "卖出",
    "hold": "持有",
    "wait": "等待",
}


class StrategyDecisionAgent:
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

    def analyze(
        self,
        *,
        ticker: str,
        analysis_date: str,
        company_context: dict[str, Any],
        technical_analysis_result: dict[str, Any],
        fundamental_analysis_result: dict[str, Any],
        event_analysis_result: dict[str, Any],
        sector_flow_analysis_result: dict[str, Any],
        strategy_style_result: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_trace = None
        trace = AgentTraceBuilder(
            agent_name="StrategyDecisionAgent",
            agent_type="agent",
            config=self.config,
            input_summary={"ticker": ticker, "analysis_date": analysis_date},
        )
        try:
            prepare_step = trace.start_step(
                name="prepare_context",
                step_type="merge",
                input_payload={"ticker": ticker, "analysis_date": analysis_date},
            )
            context = build_strategy_decision_context_payload(
                ticker=ticker,
                analysis_date=analysis_date,
                company_context=company_context,
                technical_analysis_result=technical_analysis_result,
                fundamental_analysis_result=fundamental_analysis_result,
                event_analysis_result=event_analysis_result,
                sector_flow_analysis_result=sector_flow_analysis_result,
                strategy_style_result=strategy_style_result,
            )
            trace.end_step(
                prepare_step,
                output_payload={"effective_date": context.get("effective_date"), "context_keys": sorted(context.keys())},
            )

            messages = [
                SystemMessage(content=STRATEGY_DECISION_SYSTEM_PROMPT),
                HumanMessage(content=build_strategy_decision_user_prompt(context)),
            ]
            repair_attempted = False
            for round_idx in range(2):
                llm_step = trace.start_step(
                    name=f"llm_invoke_round_{round_idx + 1}",
                    step_type="llm",
                    input_payload={"round": round_idx + 1, "message_count": len(messages)},
                )
                response = self.llm.invoke(messages)
                trace.end_step(llm_step, output_payload={"content_preview": str(response.content)[:600]})

                parse_step = trace.start_step(name="parse_json_response", step_type="parse")
                try:
                    parsed = self._parse_json_response(response.content, ticker=ticker, effective_date=context["effective_date"])
                    trace.end_step(
                        parse_step,
                        output_payload={
                            "action": parsed.get("decision", {}).get("action"),
                            "priority": parsed.get("execution_plan", {}).get("priority"),
                            "horizon": parsed.get("execution_plan", {}).get("horizon"),
                        },
                    )
                except Exception as parse_error:
                    trace.fail_step(parse_step, parse_error)
                    if not repair_attempted:
                        repair_attempted = True
                        repair_step = trace.start_step(
                            name="repair_prompt",
                            step_type="repair",
                            input_payload={"reason": "json_parse_failed", "error": str(parse_error)},
                        )
                        messages.extend(
                            [
                                response,
                                HumanMessage(
                                    content=(
                                        "你的上一版输出不是合法JSON。请严格只输出一个合法 JSON 对象，不要输出 Markdown 代码块或其他解释文字。\n"
                                        f"当前解析错误：{parse_error}"
                                    )
                                ),
                            ]
                        )
                        trace.end_step(repair_step, output_payload={"repair_attempted": True})
                        continue
                    self.last_trace = trace.finish(error=parse_error)
                    raise

                quality_step = trace.start_step(name="quality_gate", step_type="quality_gate")
                errors = self._validate_output(parsed)
                trace.end_step(
                    quality_step,
                    output_payload={"passed": not errors, "error_count": len(errors)},
                    metrics={"core_reasons_count": len(parsed.get("decision_rationale", {}).get("core_reasons", []))},
                )

                if errors and not repair_attempted:
                    repair_attempted = True
                    repair_step = trace.start_step(
                        name="repair_prompt",
                        step_type="repair",
                        input_payload={"reason": "validation_failed", "errors": errors},
                    )
                    messages.extend(
                        [
                            response,
                            HumanMessage(
                                content=(
                                    "你的上一版JSON未通过质量校验。请只输出一个修复后的完整JSON对象，并修正以下问题：\n"
                                    + "\n".join(f"- {error}" for error in errors)
                                )
                            ),
                        ]
                    )
                    trace.end_step(repair_step, output_payload={"repair_attempted": True})
                    continue

                if errors:
                    error = RuntimeError("StrategyDecisionAgent output failed quality gate: " + "; ".join(errors))
                    self.last_trace = trace.finish(error=error)
                    raise error

                self.last_trace = trace.finish(
                    output_summary={
                        "effective_date": parsed.get("effective_date"),
                        "action": parsed.get("decision", {}).get("action"),
                        "priority": parsed.get("execution_plan", {}).get("priority"),
                    }
                )
                return {
                    "analysis_result": parsed,
                    "raw_response": response.content,
                    "debug_trace": {"context": context, "validation_errors": errors} if self.debug else None,
                    "trace": self.last_trace,
                }

            error = RuntimeError("StrategyDecisionAgent exceeded max iterations without producing a valid result.")
            self.last_trace = trace.finish(error=error)
            raise error
        except Exception as error:
            if self.last_trace is None or self.last_trace.get("status") == "running":
                self.last_trace = trace.finish(error=error)
            raise

    def _parse_json(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError(f"StrategyDecisionAgent did not return valid JSON:\n{text}")
            return json.loads(text[start : end + 1])

    def _parse_json_response(self, content: str, *, ticker: str, effective_date: str) -> dict[str, Any]:
        parsed = self._parse_json(content)
        normalized = json.loads(json.dumps(STRATEGY_DECISION_OUTPUT_TEMPLATE, ensure_ascii=False))
        normalized["ticker"] = parsed.get("ticker", ticker)
        normalized["effective_date"] = parsed.get("effective_date", effective_date)
        if isinstance(parsed.get("decision"), dict):
            normalized["decision"].update(parsed["decision"])
        normalized["decision"]["label_zh"] = normalized["decision"].get("label_zh") or ACTION_LABELS.get(
            normalized["decision"].get("action", ""), ""
        )
        if isinstance(parsed.get("decision_rationale"), dict):
            normalized["decision_rationale"].update(parsed["decision_rationale"])
        if isinstance(parsed.get("execution_plan"), dict):
            normalized["execution_plan"].update(parsed["execution_plan"])
        normalized["trigger_conditions"] = parsed.get("trigger_conditions", normalized["trigger_conditions"])
        normalized["invalidations"] = parsed.get("invalidations", normalized["invalidations"])
        normalized["risk_flags"] = parsed.get("risk_flags", normalized["risk_flags"])
        normalized["decision_summary_zh"] = parsed.get("decision_summary_zh", normalized["decision_summary_zh"])
        return normalized

    def _validate_output(self, parsed: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        decision = parsed.get("decision", {})
        action = str(decision.get("action", "")).strip()
        if action not in VALID_ACTIONS:
            errors.append("decision.action 非法")
        if not str(decision.get("label_zh", "")).strip():
            errors.append("decision.label_zh 不能为空")
        if not str(decision.get("summary", "")).strip():
            errors.append("decision.summary 不能为空")
        if not isinstance(decision.get("confidence"), (int, float)):
            errors.append("decision.confidence 必须为数值")

        rationale = parsed.get("decision_rationale", {})
        if not isinstance(rationale, dict):
            errors.append("decision_rationale 必须为对象")
        else:
            if not isinstance(rationale.get("core_reasons"), list) or len(rationale["core_reasons"]) < 2:
                errors.append("decision_rationale.core_reasons 至少2条")
            if not isinstance(rationale.get("supporting_evidence"), list) or len(rationale["supporting_evidence"]) < 2:
                errors.append("decision_rationale.supporting_evidence 至少2条")
            if not isinstance(rationale.get("key_conflicts"), list):
                errors.append("decision_rationale.key_conflicts 必须为数组")

        execution = parsed.get("execution_plan", {})
        if not isinstance(execution, dict):
            errors.append("execution_plan 必须为对象")
        else:
            if str(execution.get("priority", "")).strip() not in VALID_PRIORITIES:
                errors.append("execution_plan.priority 非法")
            if str(execution.get("horizon", "")).strip() not in VALID_HORIZONS:
                errors.append("execution_plan.horizon 非法")
            if str(execution.get("positioning_bias", "")).strip() not in VALID_POSITIONING:
                errors.append("execution_plan.positioning_bias 非法")
            if not str(execution.get("preferred_setup", "")).strip():
                errors.append("execution_plan.preferred_setup 不能为空")

        for key in ("trigger_conditions", "invalidations", "risk_flags"):
            values = parsed.get(key, [])
            if not isinstance(values, list) or len(values) < 2:
                errors.append(f"{key} 至少2条")

        if not str(parsed.get("decision_summary_zh", "")).strip():
            errors.append("decision_summary_zh 不能为空")

        if action == "wait":
            text = " ".join(str(item) for item in parsed.get("trigger_conditions", []))
            if len(parsed.get("trigger_conditions", [])) < 2 or ("等待" not in str(parsed.get("decision_summary_zh", "")) and "确认" not in text):
                errors.append("action=wait 时必须明确等待的触发条件")
        if action == "buy" and str(parsed.get("execution_plan", {}).get("priority", "")) == "high":
            if len(parsed.get("risk_flags", [])) < 2:
                errors.append("高优先级 buy 必须至少提供2条 risk_flags")

        return errors
