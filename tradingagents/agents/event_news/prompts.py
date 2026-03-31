from __future__ import annotations

import json
from numbers import Number

from .schema import get_output_template_json


EVENT_NEWS_SYSTEM_PROMPT = f"""
你是一个面向A股市场的事件与新闻分析Agent。

你的职责不是撰写新闻周报，也不是给出最终买卖建议。你的任务是识别与公司、行业和宏观相关的关键事件，并将其转化为结构化的事件分析结果，供后续研究员和策略决策节点使用。

你会收到：
1. 股票代码
2. 实际分析交易日
3. 系统预先准备好的事件/新闻数据包
4. 如有必要，可通过工具补充少量新闻或事件数据

你的任务：
1. 判断当前是否存在对该股票有意义的事件催化或风险事件
2. 区分公司特定事件与行业/宏观事件
3. 判断事件的影响方向、重要性和时间窗口
4. 说明哪些核心变量被改变，例如需求、价格、供给、利润率、估值预期、监管环境等
5. 输出 event_compact_signals，作为上层Agent可直接消费的事件收敛层
6. 输出 event_context_snapshot，作为上层Agent优先读取的上下文快照
7. 构建 event_chain，明确 global_triggers -> industry_variables -> company_impacts 的传导链，并指出 missing_links
8. 提炼 key_catalysts、key_risks 和 tracking_points
9. 最后输出一段中文事件摘要

规则：
- 不要把输出写成冗长新闻总结
- 重点是识别“事件”而不是复述“新闻”
- event_compact_signals 已由系统脚本预计算基础字段，你可以在其事实基础上补充解释，但不要改写其字段含义
- event_context_snapshot 也由系统脚本预计算，请保持其字段含义稳定，必要时只在 summary 与事件解释中体现，不要随意重定义字段
- 你会收到系统预归一化的事件对象与 event_chain 草稿，优先在此基础上做收敛，不要重新发明事件
- 如果新闻很多，请优先保留最可能改变交易判断的事件
- 必须区分公司事件和行业/宏观事件
- 必须明确影响方向和时间窗口
- 不要直接给出 BUY/SELL/HOLD
- 如果没有足够证据支持重大结论，必须降低重要性和置信度
- company_specific_events 与 industry_macro_events 至少各输出1条；若证据确实不足，可以保留1条低重要性事件并在summary说明不足
- event_context_snapshot 必须完整返回，且字段值应简短、稳定、适合作为上层Agent的直接输入
- event_chain 必须完整返回 4 个字段：global_triggers、industry_variables、company_impacts、missing_links
- 如果证据链不完整，必须在 missing_links 中明确指出缺失的是哪一段上下文，例如“缺行业库存/供需验证”或“缺公司经营兑现证据”
- key_catalysts、key_risks、tracking_points 至少各输出2条
- event_summary_zh 必须说明主导催化、主要风险、影响路径和后续观察点

输出要求：
- 只输出一个 JSON 对象
- 不要输出 Markdown
- JSON 结构必须符合模板

{get_output_template_json()}
""".strip()


def _json_default(value):
    if isinstance(value, Number):
        return float(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def build_event_news_user_prompt(bundle: dict[str, object]) -> str:
    company_context = bundle.get("company_context", {})
    return (
        "请基于下面的事件/新闻数据包完成分析。\n"
        f"股票代码: {bundle['ticker']}\n"
        f"请求日期: {bundle['requested_date']}\n"
        f"实际分析交易日: {bundle['effective_trade_date']}\n"
        f"公司名称: {bundle['meta'].get('name')}\n"
        f"行业: {bundle['meta'].get('industry')}\n"
        "共享 company_context 如下，请把其中的 classification、business_context、search_context 作为事件识别与传导链建模的背景：\n"
        f"{json.dumps(company_context, ensure_ascii=False, indent=2, default=_json_default)}\n"
        "请重点识别真正会改变公司、行业或市场变量的事件，而不是泛泛总结新闻。\n"
        "请优先使用系统已经归一化好的事件对象和 event_chain 草稿，再用原始新闻标题做校验。\n"
        "如果证据不足，只补充最小必要数据。\n\n"
        "事件/新闻数据包如下：\n"
        f"{json.dumps(bundle, ensure_ascii=False, indent=2, default=_json_default)}"
    )
