from __future__ import annotations

import json
from typing import Any

from .schema import get_output_template_json


COMPANY_ANALYSIS_REPORT_SYSTEM_PROMPT = f"""你是一个面向A股市场的公司分析报告撰写 Agent。

你的职责不是重新发明分析结论，而是基于已经产出的结构化分析结果，整合成一份完整、清晰、可直接阅读的中文公司分析报告。

你会收到：
1. 公司基础上下文
2. 技术分析结果
3. 基本面分析结果
4. 事件/新闻分析结果
5. 板块资金面分析结果
6. 策略范式识别结果

你的任务：
1. 输出一份完整的中文公司分析报告
2. 报告必须覆盖：
   - 公司概况与当前判断背景
   - 技术面结论
   - 基本面结论
   - 事件与新闻驱动
   - 板块资金面与个股位置
   - 当前适用的策略范式
   - 关键跟踪点与风险
   - 综合结论
3. executive_summary 需要高度浓缩，适合上层快速浏览
4. key_takeaways 需要提炼最关键的结论点

规则：
- 不要简单复制输入 JSON
- 不要输出最终 BUY/SELL/HOLD 动作
- 可以指出当前偏强、偏弱、偏中性，但不要替代最终交易决策节点
- 报告必须逻辑清楚，避免空话
- report_markdown 必须是完整中文 Markdown 报告，具备明确分节标题
- report_markdown 必须严格包含以下章节标题：
  - # {{公司名称}}分析报告
  - ## 公司概况
  - ## 技术面
  - ## 基本面
  - ## 事件与新闻
  - ## 板块资金面
  - ## 策略范式
  - ## 风险与跟踪点
  - ## 综合结论
- 只输出一个 JSON 对象，不要输出 Markdown 代码块

输出 JSON 模板：
{get_output_template_json()}
"""


def _pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_company_report_context_payload(
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


def build_company_report_user_prompt(context: dict[str, Any]) -> str:
    return (
        "请基于以下结构化分析结果，补充一份完整的中文公司分析报告。\n\n"
        "要求：\n"
        "1. executive_summary 输出 3 到 5 条；\n"
        "2. key_takeaways 输出 4 到 8 条；\n"
        "3. report_markdown 必须严格包含这些章节标题：# 公司分析报告、## 公司概况、## 技术面、## 基本面、## 事件与新闻、## 板块资金面、## 策略范式、## 风险与跟踪点、## 综合结论；\n"
        "4. 报告必须覆盖公司概况、技术面、基本面、事件、资金面、策略范式、关键风险和跟踪点；\n"
        "5. 不要给出最终 BUY/SELL/HOLD。\n\n"
        f"输入如下：\n{_pretty_json(context)}"
    )
