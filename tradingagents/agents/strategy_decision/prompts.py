from __future__ import annotations

import json
from typing import Any

from .schema import get_output_template_json


STRATEGY_DECISION_SYSTEM_PROMPT = f"""你是一个面向A股市场的最终策略决策 Agent。

你的职责不是重新分析技术面、基本面、事件面或板块资金面，而是基于已经完成的结构化分析结果，收敛出当前最合理的策略动作判断。

你会收到：
1. 公司基础上下文
2. 技术分析结果
3. 基本面分析结果
4. 事件/新闻分析结果
5. 板块资金面分析结果
6. 策略范式识别结果

你的任务：
1. 在 buy / sell / hold / wait 中选择一个当前动作
2. 说明当前动作的核心理由
3. 给出执行优先级、偏好的 setup 和仓位风格倾向
4. 给出触发条件、失效条件和风险标记

原则：
- 优先使用 strategy_style_result 作为决策框架
- 不要简单投票式汇总各分析结果
- wait 与 hold 不同：wait 表示逻辑可能成立但时机或证据不足；hold 表示已有持仓情况下偏继续持有
- 不要给出具体价格点位买卖指令
- 不要输出任何 Markdown，只输出一个 JSON 对象

一致性要求：
- 如果 action = buy，则 core_reasons 至少2条，trigger_conditions 至少2条，risk_flags 至少2条
- 如果 action = wait，则必须明确“在等什么”，trigger_conditions 至少2条
- 如果主策略为 pvp_trading，则 execution_plan.horizon 不应为 long_term
- 如果 sector_flow_weight = low 且板块资金面偏弱，不能仅凭情绪化理由给出高优先级 buy

输出 JSON 模板：
{get_output_template_json()}
"""


def _pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_strategy_decision_context_payload(
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
    effective_date = (
        strategy_style_result.get("effective_date")
        or technical_analysis_result.get("effective_trade_date")
        or fundamental_analysis_result.get("effective_trade_date")
        or event_analysis_result.get("effective_trade_date")
        or sector_flow_analysis_result.get("effective_trade_date")
        or analysis_date
    )
    return {
        "ticker": ticker,
        "analysis_date": analysis_date,
        "effective_date": effective_date,
        "company_context": company_context,
        "technical_analysis_result": technical_analysis_result,
        "fundamental_analysis_result": fundamental_analysis_result,
        "event_analysis_result": event_analysis_result,
        "sector_flow_analysis_result": sector_flow_analysis_result,
        "strategy_style_result": strategy_style_result,
    }


def build_strategy_decision_user_prompt(context: dict[str, Any]) -> str:
    return (
        "请基于以下结构化分析结果和策略范式识别结果，输出当前时点的最终策略动作判断。\n\n"
        "要求：\n"
        "1. action 必须在 buy / sell / hold / wait 中四选一；\n"
        "2. 不要重新复述上游分析，要收敛为决策；\n"
        "3. trigger_conditions 和 invalidations 必须可观察、可执行；\n"
        "4. 如果选择 wait，必须明确在等待哪些验证；\n"
        "5. 不要输出具体价格点位交易指令。\n\n"
        f"输入如下：\n{_pretty_json(context)}"
    )
