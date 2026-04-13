from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.tracing import AgentTraceBuilder

from ..utils import parse_json_object
from .prompts import (
    STRATEGY_STYLE_SYSTEM_PROMPT,
    build_strategy_style_context_payload,
    build_strategy_style_user_prompt,
)
from .schema import STRATEGY_STYLE_OUTPUT_TEMPLATE


VALID_PRIMARY_TYPES = {
    "pb_roe_investing",
    "macro_cycle_investing",
    "prosperity_investing",
    "tech_revolution_investing",
    "pvp_trading",
}
VALID_HORIZONS = {"short_term", "medium_term", "long_term"}
VALID_WEIGHTS = {"high", "medium", "low"}
STRATEGY_LABELS = {
    "pb_roe_investing": "PB-ROE投资",
    "macro_cycle_investing": "宏观周期投资",
    "prosperity_investing": "景气投资",
    "tech_revolution_investing": "技术革命投资",
    "pvp_trading": "PVP交易",
}


class StrategyStyleAgent:
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
    ) -> dict[str, Any]:
        self.last_trace = None
        trace = AgentTraceBuilder(
            agent_name="StrategyStyleAgent",
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
            context = build_strategy_style_context_payload(
                ticker=ticker,
                analysis_date=analysis_date,
                company_context=company_context,
                technical_analysis_result=technical_analysis_result,
                fundamental_analysis_result=fundamental_analysis_result,
                event_analysis_result=event_analysis_result,
                sector_flow_analysis_result=sector_flow_analysis_result,
            )
            trace.end_step(
                prepare_step,
                output_payload={
                    "effective_date": context.get("effective_date"),
                    "context_keys": sorted(context.keys()),
                },
            )

            messages = [
                SystemMessage(content=STRATEGY_STYLE_SYSTEM_PROMPT),
                HumanMessage(content=build_strategy_style_user_prompt(context)),
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
                parsed = self._parse_json_response(response.content, ticker=ticker, effective_date=context["effective_date"])
                trace.end_step(
                    parse_step,
                    output_payload={
                        "primary_strategy": parsed.get("primary_strategy", {}).get("type"),
                        "secondary_count": len(parsed.get("secondary_strategies", [])),
                        "holding_horizon": parsed.get("holding_horizon", {}).get("type"),
                    },
                )

                quality_step = trace.start_step(name="quality_gate", step_type="quality_gate")
                errors = self._validate_output(parsed)
                trace.end_step(
                    quality_step,
                    output_payload={"passed": not errors, "error_count": len(errors)},
                    metrics={"secondary_count": len(parsed.get("secondary_strategies", []))},
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
                    error = RuntimeError("StrategyStyleAgent output failed quality gate: " + "; ".join(errors))
                    self.last_trace = trace.finish(error=error)
                    raise error

                self.last_trace = trace.finish(
                    output_summary={
                        "effective_date": parsed.get("effective_date"),
                        "primary_strategy": parsed.get("primary_strategy", {}).get("type"),
                        "holding_horizon": parsed.get("holding_horizon", {}).get("type"),
                    }
                )
                return {
                    "analysis_result": parsed,
                    "raw_response": response.content,
                    "debug_trace": {"context": context, "validation_errors": errors} if self.debug else None,
                    "trace": self.last_trace,
                }

            error = RuntimeError("StrategyStyleAgent exceeded max iterations without producing a valid result.")
            self.last_trace = trace.finish(error=error)
            raise error
        except Exception as error:
            if self.last_trace is None or self.last_trace.get("status") == "running":
                self.last_trace = trace.finish(error=error)
            raise

    def _parse_json(self, content: str) -> dict[str, Any]:
        return parse_json_object(content, source="StrategyStyleAgent output")

    def _parse_json_response(self, content: str, *, ticker: str, effective_date: str) -> dict[str, Any]:
        parsed = self._parse_json(content)
        normalized = json.loads(json.dumps(STRATEGY_STYLE_OUTPUT_TEMPLATE, ensure_ascii=False))
        normalized["ticker"] = parsed.get("ticker", ticker)
        normalized["effective_date"] = parsed.get("effective_date", effective_date)

        if isinstance(parsed.get("primary_strategy"), dict):
            normalized["primary_strategy"].update(parsed["primary_strategy"])
        normalized["primary_strategy"]["label_zh"] = normalized["primary_strategy"].get(
            "label_zh"
        ) or STRATEGY_LABELS.get(normalized["primary_strategy"].get("type", ""), "")

        secondary = parsed.get("secondary_strategies", [])
        if isinstance(secondary, list):
            normalized["secondary_strategies"] = []
            for item in secondary[:2]:
                if not isinstance(item, dict):
                    continue
                strategy_type = str(item.get("type", "")).strip()
                normalized["secondary_strategies"].append(
                    {
                        "type": strategy_type,
                        "label_zh": item.get("label_zh") or STRATEGY_LABELS.get(strategy_type, ""),
                        "summary": item.get("summary", ""),
                        "weight": item.get("weight", 0.0),
                    }
                )

        if isinstance(parsed.get("strategy_rationale"), dict):
            normalized["strategy_rationale"].update(parsed["strategy_rationale"])
        normalized["decision_priority_variables"] = parsed.get(
            "decision_priority_variables", normalized["decision_priority_variables"]
        )
        normalized["decision_kpis"] = parsed.get("decision_kpis", normalized["decision_kpis"])
        normalized["strategy_constraints"] = parsed.get(
            "strategy_constraints", normalized["strategy_constraints"]
        )
        if isinstance(parsed.get("holding_horizon"), dict):
            normalized["holding_horizon"].update(parsed["holding_horizon"])
        normalized["invalidations"] = parsed.get("invalidations", normalized["invalidations"])
        if isinstance(parsed.get("strategy_routing"), dict):
            normalized["strategy_routing"].update(parsed["strategy_routing"])
        normalized["strategy_summary_zh"] = parsed.get("strategy_summary_zh", normalized["strategy_summary_zh"])
        return normalized

    def _validate_output(self, parsed: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        primary = parsed.get("primary_strategy", {})
        primary_type = str(primary.get("type", "")).strip()
        if primary_type not in VALID_PRIMARY_TYPES:
            errors.append("primary_strategy.type 非法或为空")
        if not str(primary.get("summary", "")).strip():
            errors.append("primary_strategy.summary 不能为空")
        if not str(primary.get("label_zh", "")).strip():
            errors.append("primary_strategy.label_zh 不能为空")
        if not isinstance(primary.get("confidence"), (int, float)):
            errors.append("primary_strategy.confidence 必须为数值")
        elif float(primary.get("confidence")) < 0 or float(primary.get("confidence")) > 1:
            errors.append("primary_strategy.confidence 必须位于0到1之间")

        secondary = parsed.get("secondary_strategies", [])
        if not isinstance(secondary, list):
            errors.append("secondary_strategies 必须为数组")
        else:
            if len(secondary) > 2:
                errors.append("secondary_strategies 最多允许2个")
            for item in secondary:
                if not isinstance(item, dict):
                    errors.append("secondary_strategies 内元素必须为对象")
                    continue
                if str(item.get("type", "")).strip() not in VALID_PRIMARY_TYPES:
                    errors.append("secondary_strategies.type 非法")
                if not str(item.get("summary", "")).strip():
                    errors.append("secondary_strategies.summary 不能为空")
                if not isinstance(item.get("weight"), (int, float)):
                    errors.append("secondary_strategies.weight 必须为数值")
                elif float(item.get("weight")) <= 0 or float(item.get("weight")) > 1:
                    errors.append("secondary_strategies.weight 必须位于0到1之间且大于0")

        rationale = parsed.get("strategy_rationale", {})
        if not isinstance(rationale, dict):
            errors.append("strategy_rationale 必须为对象")
        else:
            if not isinstance(rationale.get("why_this_strategy"), list) or len(rationale["why_this_strategy"]) < 2:
                errors.append("strategy_rationale.why_this_strategy 至少2条")
            if not isinstance(rationale.get("why_not_others"), list) or len(rationale["why_not_others"]) < 2:
                errors.append("strategy_rationale.why_not_others 至少2条")

        for key in ("decision_priority_variables", "decision_kpis"):
            values = parsed.get(key, [])
            if not isinstance(values, list) or len(values) < 3 or len(values) > 5:
                errors.append(f"{key} 需要3到5条")
            elif any(not str(item).strip() for item in values):
                errors.append(f"{key} 不能包含空项")

        constraints = parsed.get("strategy_constraints", [])
        if not isinstance(constraints, list) or len(constraints) < 2:
            errors.append("strategy_constraints 至少2条")

        horizon = parsed.get("holding_horizon", {})
        if not isinstance(horizon, dict):
            errors.append("holding_horizon 必须为对象")
        else:
            if str(horizon.get("type", "")).strip() not in VALID_HORIZONS:
                errors.append("holding_horizon.type 非法")
            if not str(horizon.get("summary", "")).strip():
                errors.append("holding_horizon.summary 不能为空")

        invalidations = parsed.get("invalidations", [])
        if not isinstance(invalidations, list) or len(invalidations) < 2 or len(invalidations) > 4:
            errors.append("invalidations 需要2到4条")

        routing = parsed.get("strategy_routing", {})
        if not isinstance(routing, dict):
            errors.append("strategy_routing 必须为对象")
        else:
            for key in ("technical_weight", "fundamental_weight", "event_weight", "sector_flow_weight"):
                if str(routing.get(key, "")).strip() not in VALID_WEIGHTS:
                    errors.append(f"strategy_routing.{key} 非法")

        if not str(parsed.get("strategy_summary_zh", "")).strip():
            errors.append("strategy_summary_zh 不能为空")

        errors.extend(self._validate_consistency(parsed))
        return errors

    def _validate_consistency(self, parsed: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        primary_type = str(parsed.get("primary_strategy", {}).get("type", "")).strip()
        horizon = str(parsed.get("holding_horizon", {}).get("type", "")).strip()
        routing = parsed.get("strategy_routing", {})
        variables = " ".join(str(item) for item in parsed.get("decision_priority_variables", []))

        if primary_type == "pvp_trading" and horizon == "long_term":
            errors.append("pvp_trading 不应对应 long_term 持有周期")
        if primary_type == "pb_roe_investing" and routing.get("fundamental_weight") == "low":
            errors.append("pb_roe_investing 的 fundamental_weight 不应为 low")
        if primary_type == "pvp_trading" and routing.get("sector_flow_weight") == "low":
            errors.append("pvp_trading 的 sector_flow_weight 不应为 low")
        if primary_type == "macro_cycle_investing":
            if sum(term in variables for term in ["价格", "供给", "库存", "周期", "宏观", "油价", "铜价", "铝价"]) < 2:
                errors.append("macro_cycle_investing 的 decision_priority_variables 缺少周期变量")
        if primary_type == "prosperity_investing":
            if sum(term in variables for term in ["订单", "产能", "资本开支", "库存", "价格", "景气"]) < 2:
                errors.append("prosperity_investing 的 decision_priority_variables 缺少景气变量")
        if primary_type == "tech_revolution_investing":
            if sum(term in variables for term in ["渗透率", "技术", "成本", "新需求", "产业化", "客户验证"]) < 2:
                errors.append("tech_revolution_investing 的 decision_priority_variables 缺少技术革命变量")
        return errors
