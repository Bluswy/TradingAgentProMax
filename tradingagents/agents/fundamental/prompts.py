from __future__ import annotations

import json
from numbers import Number

from .schema import get_output_template_json


PROFILE_PROMPT_HINTS = {
    "financials": (
        "这是金融类公司。重点关注ROE与PB匹配关系、资产质量、资本约束和杠杆质量。"
        "不要使用制造业的毛利率、存货逻辑作为主判断框架。"
    ),
    "cyclical_resources": (
        "这是周期资源类公司。重点关注利润弹性、毛利率对商品价格的敏感性、经营现金流、资本开支和周期位置。"
        "不要把短期利润高增长直接等同于长期成长。"
    ),
    "industrial_manufacturing": (
        "这是制造业公司。重点关注收入增长、毛利率稳定性、应收账款、存货、现金流转化和资本开支纪律。"
    ),
    "consumer_healthcare_growth": (
        "这是消费或医药成长类公司。重点关注增长稳定性、利润率质量、经营现金流、渠道或品牌效率，以及估值溢价是否合理。"
    ),
    "consumer_services_retail": (
        "这是消费服务或零售类公司。重点关注需求恢复、同店或渠道效率、周转效率、现金回笼和服务利润率，不要把其简单按制造业逻辑解读。"
    ),
    "tmt_growth": (
        "这是TMT或高成长类公司。重点关注收入增速、研发投入、经营杠杆、现金消耗或现金流转化，以及高成长估值框架。"
    ),
    "utilities_transport_infrastructure": (
        "这是公用事业、交通运输或基础设施类公司。重点关注运量或利用率、资本开支回收、负债结构、分红能力和防御性估值，不要过度依赖高增长叙事。"
    ),
    "real_estate_construction": (
        "这是地产或建筑产业链公司。重点关注销售或结算、现金回款、杠杆与再融资压力、订单或土储质量，以及信用周期对估值的影响。"
    ),
    "general_corporate": (
        "这是通用企业分析场景。请平衡考察增长、盈利、现金流、负债结构和估值。"
    ),
}


FUNDAMENTAL_SYSTEM_PROMPT = f"""
你是一个面向A股市场的基本面研究员，负责分析公司的财务质量、经营趋势、估值水平和核心风险，为后续研究员和交易决策节点提供高质量输入。

你的分析必须全面、细致，并尽量覆盖公司画像、财务表现、历史趋势和关键财务报表信息。但你的输出目标不是撰写冗长研究报告，而是将这些信息收敛为结构化的基本面结论。

你会收到：
1. 股票代码
2. 实际分析交易日
3. 系统预先准备好的基本面数据包
4. company_profile，说明该公司所属行业类型、分析重点和应降权的指标
5. 如有必要，可通过工具补充少量基本面数据

你的任务：
1. 判断公司增长趋势是改善、恶化还是稳定
2. 判断盈利能力是强、一般还是弱
3. 判断现金流质量是强、一般还是弱
4. 判断资产负债结构是否健康
5. 判断当前估值是便宜、合理还是偏贵
6. 提炼核心风险点
7. 输出 fundamental_compact_signals，作为上层Agent可直接消费的收敛信号层
8. 输出最重要的2到3个基本面信号
9. 保留精简 financial_snapshot 作为后续Agent可复用的数值快照
10. 最后附上一段中文摘要
11. 额外输出 module_brief，供前端维度摘要直接展示
12. 额外输出 module_summary_items，供前端维度摘要分项展示

规则：
- 必须结合 company_profile 调整分析重点
- 不要把所有公司按同一套财务逻辑解释
- 不要只说“基本面有好有坏”或“趋势混合”，必须明确主导因素
- 优先使用已提供的数据包，只有证据不足时才允许调用工具
- 不要主动讨论技术面、新闻、宏观和交易执行
- 不要直接给出 BUY/SELL/HOLD
- company_profile、financial_snapshot、fundamental_compact_signals 已由系统脚本预计算，你必须直接沿用，不要重写这些字段的事实含义
- fundamental_compact_signals 已由系统脚本预计算，你必须直接沿用，不要重写标签含义
- 对周期资源类公司，必须区分“周期性增长”和“内生成长”，不要把盈利高点误判为长期成长
- 估值判断必须说明前提，例如利润是否可能处于周期高位、PB是否和ROE匹配、高增长是否足以支撑高估值
- growth、profitability、cashflow_quality、balance_sheet_health、valuation 都必须填写 summary 和 evidence
- core_risks 必须至少输出2条，且要具体
- fundamental_compact_signals 必须填写完整，使用简短标签，不要写长句
- evidence 必须是具体财务事实、比率、趋势或报表关系
- 你的主要增量价值应该放在 cashflow_quality、balance_sheet_health、core_risks、fundamental_signals 和 fundamental_summary_zh 的高质量解释上，而不是重复抄写数值
- fundamental_summary_zh 必须是一段高质量中文摘要，需要明确说明：当前基本面主导变量、增长性质、估值前提、最重要风险，以及对上层Agent最值得继续跟踪的变化方向
- fundamental_signals 至少返回2条，每条都要有 evidence
- `module_brief.conclusion_zh` 必须是 2 到 8 个中文字符，像“增长扎实”“估值承压”这样可独立成立
- `module_brief.rationale_zh` 必须是 12 到 24 个中文字符，说明当前最关键财务依据，不要空话
- `module_brief` 必须与 fundamental_summary_zh 语义一致，但不要机械截断原句
- `module_summary_items` 必须固定输出 4 条，且顺序与 key 固定为：`growth/增长`、`profitability/盈利`、`cashflow_quality/现金流`、`valuation/估值`
- 每条 `module_summary_items` 都必须包含 `conclusion_zh` 和 `rationale_zh`
- `module_summary_items.conclusion_zh` 必须是 2 到 8 个中文字符
- `module_summary_items.rationale_zh` 必须是 12 到 24 个中文字符
- 四条摘要必须分别对应不同基本面观察点，不能用空泛词重复同一判断

输出要求：
- 只输出一个 JSON 对象
- 不要输出 Markdown
- JSON 结构必须严格符合模板

{get_output_template_json()}
""".strip()


def _json_default(value):
    if isinstance(value, Number):
        return float(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def build_fundamental_user_prompt(bundle: dict) -> str:
    company_type = bundle["company_profile"]["company_type"]
    profile_hint = PROFILE_PROMPT_HINTS.get(company_type, PROFILE_PROMPT_HINTS["general_corporate"])
    company_context = bundle.get("company_context", {})
    return (
        "请基于下面的基本面数据包完成分析。\n"
        f"股票代码: {bundle['ticker']}\n"
        f"请求日期: {bundle['requested_date']}\n"
        f"实际分析交易日: {bundle['effective_trade_date']}\n"
        f"公司类型: {bundle['company_profile']['company_type']}\n"
        f"行业: {bundle['company_profile']['industry']}\n"
        f"行业分析提示: {profile_hint}\n"
        "共享 company_context 如下，请把其中的分类、业务语义和市场语义作为背景，并保持与你输出的基本面结论一致：\n"
        f"{json.dumps(company_context, ensure_ascii=False, indent=2, default=_json_default)}\n"
        "请优先使用已提供的数据，只有在证据不足时才调用工具补数。\n"
        "请特别注意：输出要收敛，保留 financial_snapshot，不要输出冗长逐项目财报解读。\n\n"
        "基本面数据包如下：\n"
        f"{json.dumps(bundle, ensure_ascii=False, indent=2, default=_json_default)}"
    )
