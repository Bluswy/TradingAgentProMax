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
1. 先显式判断“价格行为 + 成交量 + 催化因素”之间的关系：当前催化是否被价格行为确认、是否得到量能配合、还是仍存在背离
2. 在 buy / sell / hold / wait 中选择一个当前动作
3. 说明当前动作的核心理由
4. 给出执行优先级、偏好的 setup 和仓位风格倾向
5. 产出“最强依据”“冲突依据”“模块贡献”“跟踪清单”“结构化失效条件”“结构化风险”
6. 给出触发条件、失效条件和风险标记

原则：
- 优先使用 strategy_style_result 作为决策框架
- 必须显式完成“催化 -> 价格行为 -> 成交量确认”的融合判断，而不是只做泛化汇总
- 不要简单投票式汇总各分析结果
- wait 与 hold 不同：wait 表示逻辑可能成立但时机或证据不足；hold 表示已有持仓情况下偏继续持有
- 不要给出具体价格点位买卖指令
- 不要输出任何 Markdown，只输出一个 JSON 对象

一致性要求：
- 你必须在 `decision_rationale.core_reasons` 或 `decision_summary_zh` 中明确回答以下三个问题：
  1. 当前主要催化是什么，偏正向、负向还是混合
  2. 价格行为是在确认催化、部分确认，还是与催化背离
  3. 成交量是在支持当前价格响应，还是没有形成确认
- 如果主要催化偏正向，但技术面表现为震荡/走弱，或 `volume_confirmation` 未确认，则动作应更偏 `wait` 或低优先级处理
- 如果主要催化偏负向，且价格走弱并伴随量能确认，则不能轻易给出乐观动作
- 只有当催化逻辑、价格行为和量能确认大体一致时，才适合给出更积极的动作
- 如果 action = buy，则 core_reasons 至少2条，trigger_conditions 至少2条，risk_flags 至少2条
- 如果 action = wait，则必须明确“在等什么”，trigger_conditions 至少2条
- 如果主策略为 pvp_trading，则 execution_plan.horizon 不应为 long_term
- 如果 sector_flow_weight = low 且板块资金面偏弱，不能仅凭情绪化理由给出高优先级 buy
- `top_supporting_evidence` 只保留最重要的 2 到 3 条，每条都必须写清楚事实和来源模块；这些证据必须直接支持“当前最终动作”，而不是泛泛支持公司长期故事
- 如果 action = wait，`top_supporting_evidence` 应优先解释“为什么现在不宜追高/不宜立即执行”，而不是只写看多逻辑
- 如果 action = buy / hold / sell，`top_supporting_evidence` 应优先解释为什么当前时点适合这个动作，而不是相反动作
- `top_conflicting_evidence` 用于暴露当前最重要的反对证据；它应该和 `top_supporting_evidence` 一起解释“为什么是这个动作，而不是相反动作”。没有明显冲突时，也要给出至少1条“仍需验证”的约束
- `module_contributions` 必须覆盖 technical / fundamental / event_news / sector_flow 四个模块，并标明 supporting / neutral / conflicting
- `watchlist` 必须是后续最值得追踪的 2 到 3 个变量，每条都要写清楚观察窗口，以及验证通过/不通过分别意味着什么
- `invalidations_structured` 不能只是重复原文，必须拆成“失效类型 + 条件 + 触发后动作”
- `primary_risk` 必须回答“最可能错在哪里”，并说明风险如何传导到结论或赔率；风险标题应使用直白中文，避免过多行业黑话
- `secondary_risks` 至少1条，用于补充次要但不能忽视的风险

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
        "3. 必须先做一轮显式融合判断：主要催化是什么，价格行为是否确认，成交量是否确认；\n"
        "4. 你的核心理由里必须体现这轮融合判断，而不是只罗列上游结论；\n"
        "5. 你必须显式输出最强依据、模块贡献、watchlist、结构化失效条件、结构化风险；\n"
        "6. trigger_conditions 和 invalidations 必须可观察、可执行；\n"
        "7. 如果选择 wait，必须明确在等待哪些验证；\n"
        "8. `top_supporting_evidence` 必须服务于最终动作本身，例如 action=wait 时，要解释为什么现在要等，而不是只解释公司为什么值得关注；\n"
        "9. 风险标题要直白，优先用用户一眼能看懂的表达；\n"
        "10. 不要输出具体价格点位交易指令。\n\n"
        f"输入如下：\n{_pretty_json(context)}"
    )
