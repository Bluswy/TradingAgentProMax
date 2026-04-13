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
    COMPANY_ANALYSIS_REPORT_SYSTEM_PROMPT,
    build_company_report_context_payload,
    build_company_report_user_prompt,
)
from .schema import COMPANY_ANALYSIS_REPORT_OUTPUT_TEMPLATE


class CompanyAnalysisReportAgent:
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
            agent_name="CompanyAnalysisReportAgent",
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
            context = build_company_report_context_payload(
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
                SystemMessage(content=COMPANY_ANALYSIS_REPORT_SYSTEM_PROMPT),
                HumanMessage(content=build_company_report_user_prompt(context)),
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
                    parsed = self._parse_json_response(
                        response.content, ticker=ticker, effective_date=context["effective_date"]
                    )
                    trace.end_step(
                        parse_step,
                        output_payload={
                            "report_title": parsed.get("report_title"),
                            "executive_summary_count": len(parsed.get("executive_summary", [])),
                            "key_takeaways_count": len(parsed.get("key_takeaways", [])),
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
                                        "你的上一版输出不是合法JSON。请严格遵守以下要求重新输出：\n"
                                        "1. 只输出一个合法 JSON 对象；\n"
                                        "2. 不要输出 Markdown 代码块；\n"
                                        "3. report_markdown 必须是 JSON 字符串，内部换行需要由模型正确转义；\n"
                                        "4. report_markdown 中如果需要双引号，必须使用 \\\" 转义；\n"
                                        "5. 不要在 JSON 之外输出任何解释文字；\n"
                                        f"6. 当前解析错误：{parse_error}"
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
                    metrics={"markdown_length": len(parsed.get("report_markdown", ""))},
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
                                    + "\n- report_markdown 必须严格包含这些章节标题：# 公司分析报告、## 公司概况、## 技术面、## 基本面、## 事件与新闻、## 板块资金面、## 策略范式、## 风险与跟踪点、## 综合结论"
                                )
                            ),
                        ]
                    )
                    trace.end_step(repair_step, output_payload={"repair_attempted": True})
                    continue

                if errors:
                    error = RuntimeError("CompanyAnalysisReportAgent output failed quality gate: " + "; ".join(errors))
                    self.last_trace = trace.finish(error=error)
                    raise error

                self.last_trace = trace.finish(
                    output_summary={
                        "effective_date": parsed.get("effective_date"),
                        "report_title": parsed.get("report_title"),
                        "markdown_length": len(parsed.get("report_markdown", "")),
                    }
                )
                return {
                    "analysis_result": parsed,
                    "raw_response": response.content,
                    "debug_trace": {"context": context, "validation_errors": errors} if self.debug else None,
                    "trace": self.last_trace,
                }
            error = RuntimeError("CompanyAnalysisReportAgent exceeded max iterations without producing a valid result.")
            self.last_trace = trace.finish(error=error)
            raise error
        except Exception as error:
            if self.last_trace is None or self.last_trace.get("status") == "running":
                self.last_trace = trace.finish(error=error)
            raise

    def _parse_json(self, content: str) -> dict[str, Any]:
        return parse_json_object(content, source="CompanyAnalysisReportAgent output")

    def _parse_json_response(self, content: str, *, ticker: str, effective_date: str) -> dict[str, Any]:
        parsed = self._parse_json(content)
        normalized = json.loads(json.dumps(COMPANY_ANALYSIS_REPORT_OUTPUT_TEMPLATE, ensure_ascii=False))
        normalized["ticker"] = parsed.get("ticker", ticker)
        normalized["effective_date"] = parsed.get("effective_date", effective_date)
        normalized["report_title"] = parsed.get("report_title", normalized["report_title"])
        normalized["executive_summary"] = parsed.get("executive_summary", normalized["executive_summary"])
        normalized["key_takeaways"] = parsed.get("key_takeaways", normalized["key_takeaways"])
        normalized["report_markdown"] = parsed.get("report_markdown", normalized["report_markdown"])
        return normalized

    def _validate_output(self, parsed: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not str(parsed.get("report_title", "")).strip():
            errors.append("report_title 不能为空")
        exec_sum = parsed.get("executive_summary", [])
        if not isinstance(exec_sum, list) or len(exec_sum) < 3 or len(exec_sum) > 5:
            errors.append("executive_summary 需要3到5条")
        takeaways = parsed.get("key_takeaways", [])
        if not isinstance(takeaways, list) or len(takeaways) < 4 or len(takeaways) > 8:
            errors.append("key_takeaways 需要4到8条")
        report_md = str(parsed.get("report_markdown", "")).strip()
        if not report_md:
            errors.append("report_markdown 不能为空")
        else:
            for heading in ("# ", "## 公司概况", "## 技术面", "## 基本面", "## 事件与新闻", "## 板块资金面", "## 策略范式", "## 风险与跟踪点", "## 综合结论"):
                if heading not in report_md:
                    errors.append(f"report_markdown 缺少必要章节: {heading}")
                    break
        return errors
