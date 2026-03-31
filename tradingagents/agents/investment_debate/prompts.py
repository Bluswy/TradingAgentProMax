from __future__ import annotations

import json
from typing import Any

from .schema import get_case_template_json, get_judge_template_json


BULL_SYSTEM_PROMPT = f"""你是一个A股多头论证分析角色。

你的任务不是重复输入材料，而是基于已有的结构化分析结果，提炼最强的做多逻辑。

你的职责：
1. 识别最关键的上涨驱动因素；
2. 说明这些驱动来自技术面、基本面、事件面还是板块资金面；
3. 主动回应最明显的空头风险；
4. 明确多头逻辑成立所依赖的前提。

规则：
- 不要泛泛罗列利好；
- 只保留最重要的2到4条核心论据；
- 不要忽视不利证据，必须解释为什么它们不足以推翻多头逻辑；
- 输出要服务于后续辩论收敛，而不是写成长报告；
- 只输出一个JSON对象，不要输出Markdown。

输出JSON模板：
{get_case_template_json()}
"""


BEAR_SYSTEM_PROMPT = f"""你是一个A股空头论证分析角色。

你的任务不是重复输入材料，而是基于已有的结构化分析结果，提炼最强的做空或回避逻辑。

你的职责：
1. 识别最关键的风险和脆弱点；
2. 说明这些风险来自技术面、基本面、事件面还是板块资金面；
3. 主动回应最明显的多头论据；
4. 明确空头逻辑成立所依赖的前提。

规则：
- 不要泛泛罗列风险；
- 只保留最重要的2到4条核心论据；
- 不要忽视有利证据，必须解释为什么它们不足以支撑做多；
- 输出要服务于后续辩论收敛，而不是写成长报告；
- 只输出一个JSON对象，不要输出Markdown。

输出JSON模板：
{get_case_template_json()}
"""


JUDGE_SYSTEM_PROMPT = f"""你是一个A股多空争议收敛角色。

你会收到：
1. 已有的结构化分析结果；
2. 多头论证；
3. 空头论证。

你的任务不是直接给出买卖建议，而是：
1. 提炼双方最强论据；
2. 明确当前最核心的冲突点；
3. 明确决定分歧的关键假设；
4. 指出仍缺失的证据；
5. 判断当前争议更偏向多头、空头还是均衡。

规则：
- 不要重新做一遍分析；
- 不要默认“多空都有道理”；
- 必须指出哪一边当前证据更强，以及为什么；
- 只输出一个JSON对象，不要输出Markdown。

输出JSON模板：
{get_judge_template_json()}
"""


def _pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_debate_context_payload(
    *,
    ticker: str,
    analysis_date: str,
    technical_analysis_result: dict[str, Any],
    fundamental_analysis_result: dict[str, Any],
    event_analysis_result: dict[str, Any],
    sector_flow_analysis_result: dict[str, Any],
) -> dict[str, Any]:
    effective_date = (
        technical_analysis_result.get("effective_trade_date")
        or fundamental_analysis_result.get("effective_trade_date")
        or event_analysis_result.get("effective_trade_date")
        or sector_flow_analysis_result.get("effective_trade_date")
        or analysis_date
    )
    return {
        "ticker": ticker,
        "analysis_date": analysis_date,
        "effective_date": effective_date,
        "technical_analysis_result": technical_analysis_result,
        "fundamental_analysis_result": fundamental_analysis_result,
        "event_analysis_result": event_analysis_result,
        "sector_flow_analysis_result": sector_flow_analysis_result,
    }


def build_bull_user_prompt(context: dict[str, Any]) -> str:
    return (
        "请基于以下结构化分析结果，生成最强做多论证。\n\n"
        "要求：\n"
        "1. 明确指出上涨驱动来自哪些维度；\n"
        "2. 主动回应最显著的空头风险；\n"
        "3. 只保留最关键的2到4条核心论据；\n"
        "4. 只输出JSON。\n\n"
        f"输入如下：\n{_pretty_json(context)}"
    )


def build_bear_user_prompt(context: dict[str, Any], bull_case: dict[str, Any]) -> str:
    payload = {
        "context": context,
        "bull_case": bull_case,
    }
    return (
        "请基于以下结构化分析结果和已有多头论证，生成最强做空或回避论证。\n\n"
        "要求：\n"
        "1. 明确指出最关键的风险和脆弱点；\n"
        "2. 必须回应多头论据，而不是忽视它；\n"
        "3. 只保留最关键的2到4条核心论据；\n"
        "4. 只输出JSON。\n\n"
        f"输入如下：\n{_pretty_json(payload)}"
    )


def build_judge_user_prompt(
    context: dict[str, Any],
    bull_case: dict[str, Any],
    bear_case: dict[str, Any],
) -> str:
    payload = {
        "context": context,
        "bull_case": bull_case,
        "bear_case": bear_case,
    }
    return (
        "请基于以下结构化分析结果、多头论证和空头论证，输出收敛后的争议结论。\n\n"
        "要求：\n"
        "1. 明确列出主冲突点；\n"
        "2. 明确关键假设；\n"
        "3. 指出仍缺失的证据；\n"
        "4. 判断当前争议更偏多头、空头还是均衡；\n"
        "5. 不要给出最终买卖建议；\n"
        "6. 只输出JSON。\n\n"
        f"输入如下：\n{_pretty_json(payload)}"
    )
