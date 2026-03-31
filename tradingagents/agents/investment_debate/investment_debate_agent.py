from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.tracing import AgentTraceBuilder

from .prompts import (
    BEAR_SYSTEM_PROMPT,
    BULL_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT,
    build_bear_user_prompt,
    build_bull_user_prompt,
    build_debate_context_payload,
    build_judge_user_prompt,
)
from .schema import (
    DEBATE_CASE_TEMPLATE,
    DEBATE_JUDGE_TEMPLATE,
    INVESTMENT_DEBATE_OUTPUT_TEMPLATE,
)


class InvestmentDebateAgent:
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
        technical_analysis_result: dict[str, Any],
        fundamental_analysis_result: dict[str, Any],
        event_analysis_result: dict[str, Any],
        sector_flow_analysis_result: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_trace = None
        trace = AgentTraceBuilder(
            agent_name="InvestmentDebateAgent",
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
            context = build_debate_context_payload(
                ticker=ticker,
                analysis_date=analysis_date,
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

            bull_step = trace.start_step(
                name="bull_case_llm",
                step_type="llm",
                input_payload={"ticker": ticker, "effective_date": context.get("effective_date")},
            )
            bull_response = self.llm.invoke(
                [
                    SystemMessage(content=BULL_SYSTEM_PROMPT),
                    HumanMessage(content=build_bull_user_prompt(context)),
                ]
            )
            trace.end_step(bull_step, output_payload={"content_preview": str(bull_response.content)[:500]})
            bull_parse_step = trace.start_step(name="parse_bull_case", step_type="parse")
            bull_case = self._parse_case_json(bull_response.content, role="bull")
            trace.end_step(
                bull_parse_step,
                output_payload={
                    "confidence": bull_case.get("confidence"),
                    "core_points_count": len(bull_case.get("core_points", [])),
                },
            )

            bear_step = trace.start_step(
                name="bear_case_llm",
                step_type="llm",
                input_payload={"ticker": ticker, "bull_case_summary": bull_case.get("summary")},
            )
            bear_response = self.llm.invoke(
                [
                    SystemMessage(content=BEAR_SYSTEM_PROMPT),
                    HumanMessage(content=build_bear_user_prompt(context, bull_case)),
                ]
            )
            trace.end_step(bear_step, output_payload={"content_preview": str(bear_response.content)[:500]})
            bear_parse_step = trace.start_step(name="parse_bear_case", step_type="parse")
            bear_case = self._parse_case_json(bear_response.content, role="bear")
            trace.end_step(
                bear_parse_step,
                output_payload={
                    "confidence": bear_case.get("confidence"),
                    "core_points_count": len(bear_case.get("core_points", [])),
                },
            )

            judge_step = trace.start_step(
                name="judge_llm",
                step_type="llm",
                input_payload={"ticker": ticker, "bull_confidence": bull_case.get("confidence"), "bear_confidence": bear_case.get("confidence")},
            )
            judge_response = self.llm.invoke(
                [
                    SystemMessage(content=JUDGE_SYSTEM_PROMPT),
                    HumanMessage(content=build_judge_user_prompt(context, bull_case, bear_case)),
                ]
            )
            trace.end_step(judge_step, output_payload={"content_preview": str(judge_response.content)[:500]})
            judge_parse_step = trace.start_step(name="parse_judge_output", step_type="parse")
            judge_output = self._parse_judge_json(judge_response.content)
            trace.end_step(
                judge_parse_step,
                output_payload={
                    "lean": judge_output.get("debate_conclusion", {}).get("lean"),
                    "main_conflicts_count": len(judge_output.get("debate_focus", {}).get("main_conflicts", [])),
                },
            )

            merge_step = trace.start_step(name="merge_output", step_type="merge")
            final_result = self._assemble_output(
                ticker=ticker,
                effective_date=context["effective_date"],
                bull_case=bull_case,
                bear_case=bear_case,
                judge_output=judge_output,
            )
            trace.end_step(
                merge_step,
                output_payload={
                    "lean": final_result.get("debate_conclusion", {}).get("lean"),
                    "summary_preview": str(final_result.get("debate_summary_zh", ""))[:300],
                },
            )

            quality_step = trace.start_step(name="quality_gate", step_type="quality_gate")
            is_sparse = self._is_sparse_output(final_result)
            trace.end_step(
                quality_step,
                output_payload={"is_sparse": is_sparse},
                metrics={"main_conflicts_count": len(final_result.get("debate_focus", {}).get("main_conflicts", []))},
            )
            if is_sparse:
                error = RuntimeError("InvestmentDebateAgent produced sparse output and failed quality gate.")
                self.last_trace = trace.finish(error=error)
                raise error

            self.last_trace = trace.finish(
                output_summary={
                    "effective_date": final_result.get("effective_date"),
                    "lean": final_result.get("debate_conclusion", {}).get("lean"),
                    "main_conflicts_count": len(final_result.get("debate_focus", {}).get("main_conflicts", [])),
                }
            )
            return {
                "analysis_result": final_result,
                "raw_response": {
                    "bull_case": bull_response.content,
                    "bear_case": bear_response.content,
                    "judge": judge_response.content,
                },
                "debug_trace": {
                    "context": context,
                    "bull_case": bull_case,
                    "bear_case": bear_case,
                    "judge_output": judge_output,
                }
                if self.debug
                else None,
                "trace": self.last_trace,
            }
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
                raise ValueError(f"InvestmentDebateAgent did not return valid JSON:\n{text}")
            return json.loads(text[start : end + 1])

    def _parse_case_json(self, content: str, role: str) -> dict[str, Any]:
        parsed = self._parse_json(content)
        normalized = json.loads(json.dumps(DEBATE_CASE_TEMPLATE, ensure_ascii=False))
        normalized.update(
            {
                "summary": parsed.get("summary", normalized["summary"]),
                "core_points": parsed.get("core_points", normalized["core_points"]),
                "key_evidence": parsed.get("key_evidence", normalized["key_evidence"]),
                "confidence": parsed.get("confidence", normalized["confidence"]),
            }
        )
        if self._is_sparse_case(normalized):
            raise RuntimeError(f"InvestmentDebateAgent {role} case is too sparse.")
        return normalized

    def _parse_judge_json(self, content: str) -> dict[str, Any]:
        parsed = self._parse_json(content)
        normalized = json.loads(json.dumps(DEBATE_JUDGE_TEMPLATE, ensure_ascii=False))
        if isinstance(parsed.get("debate_focus"), dict):
            normalized["debate_focus"].update(parsed["debate_focus"])
        if isinstance(parsed.get("debate_conclusion"), dict):
            normalized["debate_conclusion"].update(parsed["debate_conclusion"])
        normalized["debate_summary_zh"] = parsed.get(
            "debate_summary_zh", normalized["debate_summary_zh"]
        )
        if self._is_sparse_judge(normalized):
            raise RuntimeError("InvestmentDebateAgent judge output is too sparse.")
        return normalized

    def _assemble_output(
        self,
        *,
        ticker: str,
        effective_date: str,
        bull_case: dict[str, Any],
        bear_case: dict[str, Any],
        judge_output: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = json.loads(json.dumps(INVESTMENT_DEBATE_OUTPUT_TEMPLATE, ensure_ascii=False))
        normalized.update(
            {
                "ticker": ticker,
                "effective_date": effective_date,
                "bull_case": bull_case,
                "bear_case": bear_case,
                "debate_summary_zh": judge_output["debate_summary_zh"],
            }
        )
        normalized["debate_focus"].update(judge_output["debate_focus"])
        normalized["debate_conclusion"].update(judge_output["debate_conclusion"])
        return normalized

    def _is_sparse_case(self, case: dict[str, Any]) -> bool:
        if not str(case.get("summary", "")).strip():
            return True
        if not isinstance(case.get("core_points"), list) or len(case["core_points"]) < 2:
            return True
        if not isinstance(case.get("key_evidence"), list) or len(case["key_evidence"]) < 2:
            return True
        return False

    def _is_sparse_judge(self, judge_output: dict[str, Any]) -> bool:
        focus = judge_output.get("debate_focus", {})
        conclusion = judge_output.get("debate_conclusion", {})
        if not isinstance(focus, dict) or not isinstance(conclusion, dict):
            return True
        if not isinstance(focus.get("main_conflicts"), list) or len(focus["main_conflicts"]) < 1:
            return True
        if not isinstance(focus.get("critical_assumptions"), list) or len(focus["critical_assumptions"]) < 1:
            return True
        if "missing_evidence" not in focus or not isinstance(focus["missing_evidence"], list):
            return True
        if conclusion.get("lean") not in {"bullish", "bearish", "balanced"}:
            return True
        if not str(conclusion.get("summary", "")).strip():
            return True
        if not isinstance(conclusion.get("why"), list) or len(conclusion["why"]) < 2:
            return True
        if not str(judge_output.get("debate_summary_zh", "")).strip():
            return True
        return False

    def _is_sparse_output(self, parsed: dict[str, Any]) -> bool:
        if self._is_sparse_case(parsed.get("bull_case", {})):
            return True
        if self._is_sparse_case(parsed.get("bear_case", {})):
            return True
        judge_payload = {
            "debate_focus": parsed.get("debate_focus", {}),
            "debate_conclusion": parsed.get("debate_conclusion", {}),
            "debate_summary_zh": parsed.get("debate_summary_zh", ""),
        }
        return self._is_sparse_judge(judge_payload)
