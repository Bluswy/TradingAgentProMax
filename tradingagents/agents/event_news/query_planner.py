from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client


QUERY_PLANNER_OUTPUT_TEMPLATE = {
    "sensitivity_variables": [],
    "company_query": "",
    "industry_query": "",
    "global_event_query": "",
    "query_rationale": {
        "company": "",
        "industry": "",
        "global": "",
    },
}


QUERY_PLANNER_FEW_SHOTS = """
示例1：招商轮船（油运/航运）
输入：
- 股票代码：601872.SH
- 公司名称：招商轮船
- 行业：水运
- 公司类型：utilities_transport_infrastructure
好的输出示例：
{
  "sensitivity_variables": ["油轮运价", "BDTI/BCTI", "OPEC供给政策", "红海/霍尔木兹地缘风险", "战争险与绕航成本"],
  "company_query": "招商轮船 近期公告 业绩快报 船队扩张 长租合同 新船交付 融资 风险",
  "industry_query": "水运 油运 近期 运价 BDTI BCTI VLCC 供需 交付 拆船 绕航 成本",
  "global_event_query": "近期 红海 霍尔木兹 OPEC 原油贸易流向 油轮 运价 战争险 绕航",
  "query_rationale": {
    "company": "覆盖业绩、船队扩张、合同与融资风险。",
    "industry": "覆盖油运行业最关键的中观变量：运价、供需、交付、拆船、成本。",
    "global": "覆盖地缘触发与运价/成本传导。"
  }
}

示例2：卫星化学（化工/周期成长）
输入：
- 股票代码：002648.SZ
- 公司名称：卫星化学
- 行业：化工原料
- 公司类型：cyclical_resources
好的输出示例：
{
  "sensitivity_variables": ["丙烷价格", "PDH价差", "乙烯/丙烯价格", "化工品出口", "开工率与检修"],
  "company_query": "卫星化学 近期 公告 业绩 检修 开工率 项目投产 出口 合同 风险",
  "industry_query": "化工原料 近期 丙烷 PDH 价差 乙烯 丙烯 开工率 检修 出口 需求",
  "global_event_query": "近期 原油 丙烷 关税 美元指数 出口 化工品 价差 成本 需求",
  "query_rationale": {
    "company": "覆盖业绩、装置运行、项目投产和风险事件。",
    "industry": "覆盖化工链的价格、价差、开工率、检修和出口需求。",
    "global": "覆盖油气成本与外贸/汇率对化工盈利的传导。"
  }
}

示例3：长川科技（半导体设备）
输入：
- 股票代码：300604.SZ
- 公司名称：长川科技
- 行业：半导体
- 公司类型：tmt_growth
好的输出示例：
{
  "sensitivity_variables": ["半导体设备需求", "晶圆厂资本开支", "国产替代", "先进封装", "出口限制"],
  "company_query": "长川科技 近期 公告 业绩 订单 客户 验证 新品 国产替代 监管 风险",
  "industry_query": "半导体 近期 设备需求 资本开支 国产替代 先进封装 竞争格局 技术进展",
  "global_event_query": "近期 芯片 出口限制 AI 资本开支 半导体设备 需求 供应链 成本",
  "query_rationale": {
    "company": "覆盖订单、客户验证、新品和业绩兑现。",
    "industry": "覆盖资本开支、国产替代和技术进展等中观变量。",
    "global": "覆盖全球科技政策与需求链传导。"
  }
}

示例4：明泰铝业（铝加工/有色）
输入：
- 股票代码：601677.SH
- 公司名称：明泰铝业
- 行业：铝
- 公司类型：cyclical_resources
好的输出示例：
{
  "sensitivity_variables": ["铝价", "加工费", "库存", "需求", "出口政策", "电价成本"],
  "company_query": "明泰铝业 近期 公告 业绩 订单 扩产 出口 融资 风险",
  "industry_query": "铝 近期 价格 加工费 库存 需求 出口 电价 成本 景气",
  "global_event_query": "近期 铝价 美元指数 关税 出口 需求 库存 成本 电价",
  "query_rationale": {
    "company": "覆盖业绩、订单、扩产与财务风险。",
    "industry": "覆盖铝链的价格、加工费、库存、需求与成本。",
    "global": "覆盖大宗商品价格、汇率、关税与出口传导。"
  }
}
""".strip()


QUERY_PLANNER_SYSTEM_PROMPT = f"""
你是一个A股事件检索查询规划器。

你的任务不是分析新闻，也不是给出投资建议。你的唯一职责是：根据目标公司信息，生成一组高质量的金融资讯检索 query，用于后续的事件与新闻搜索。

你必须生成三层 query，每层只输出 1 条最高质量的 query：
1. 公司层 query：用于检索该公司的直接相关新闻、公告、研报、业绩、订单、资本运作、监管与风险事件
2. 行业层 query：用于检索该公司所属行业的中观变量变化，包括政策、供需、价格/景气、库存/资本开支、竞争格局或技术进展
3. 全球事件层 query：用于检索可能影响该公司的国际事件、地缘风险、商品价格、运输、汇率、利率、政策变化等外部冲击

生成规则：
- query 必须适合中文金融资讯搜索，不要生成英文搜索引擎式 query
- query 必须尽量具体，围绕影响变量展开，而不是泛泛搜索最新新闻
- 优先关注能影响公司基本面、股价走势和行业景气度的事件
- 你会收到系统补充的最小上下文：公司介绍，以及所属板块/行业层级信息。请优先利用这些信息细化赛道语义，不要只停留在粗行业标签
- 如果粗行业标签较宽，而最小上下文已经暴露出更具体的细分赛道、主产品或主业务线，必须优先使用这些更具体的词，不要退回到“水运、化工原料、电子元件”这类大行业词
- 如果公司是多业务组合，不要为了“看起来全面”把 3 个以上弱相关子赛道硬塞进同一条行业 query；应优先选择最影响利润与估值的主线业务，最多补充 1 个强相关次主线
- 如果不同子业务对应完全不同的资讯生态或变量体系，应宁可聚焦主线，也不要把多条业务线混成一条噪声很高的 query
- 对周期股，要重点考虑商品价格、供需、运输、库存、政策和地缘因素
- 对成长股，要重点考虑需求、技术进展、资本开支、客户验证和监管政策
- 对金融股，要重点考虑监管、利率、资产质量和资本约束
- 不要生成重复 query
- 每个 query 保持简洁，但必须覆盖足够维度，尽量由公司名/股票代码/行业名 + 变量/事件关键词构成
- 公司层 query 需要兼顾正向经营事件和负向风险事件，不要只搜单一负面词，也不要退化成泛新闻
- 如果公司介绍和所属板块已经提供了更具体的产品、赛道或业务方向，必须优先使用这些更具体的词，避免停留在“元器件、水运、化工原料”这类过宽行业名词
- 行业层 query 必须更像“变量检索”而不是“行业新闻检索”，优先覆盖以下变量中的多个：政策、供给、需求、价格/景气、库存/资本开支、竞争格局/技术进展
- 全球事件层 query 不能写成抽象宏观分析句，必须包含 2 到 4 个具体事件词或资产词，例如：霍尔木兹海峡、OPEC、原油、油价、航运、美元指数、关税、红海、铜价、天然气
- 全球事件层 query 必须同时包含“触发因素词”和“传导变量词”，例如：霍尔木兹海峡/OPEC/红海/美元指数 + 供给/价格/运价/保险/库存/成本/汇率
- 三层 query 都必须带时间窗表达，例如“最近10天”或“最近30天”
- 如果 business_hint 为空，不要臆造公司主营细节，基于股票名称、行业、公司类型和常见影响变量生成 query
- 你的目标不是写最优雅的 query，而是写最可能召回“高价值、低噪声、可构成事件传导链”的 query
- 如果行业很宽，仍要优先覆盖股票分析最关键的 2 到 4 个变量，不要贪多
- query 必须更像“中文财经资讯标题关键词簇”，而不是完整分析句。优先输出名词和变量词，减少虚词和连接词
- 某些行业应优先使用“行业原生指标/术语”而非泛词。例如：
  - 航运/油运：优先用 油运、油轮、VLCC、AFRAMAX、BDTI、TCE、订单、交付、拆船、绕航、战争险，而不是把油运/干散货/LNG/集运全部并列
  - 有色/资源：优先用 具体品种 + 价格/加工费/库存/供给/需求/关税/汇率，而不是笼统写“有色行业”
  - 半导体设备：优先用 设备需求、资本开支、国产替代、先进封装、验证/订单，而不是泛泛写“半导体景气”

建议的思考步骤：
1. 先识别这家公司盈利最敏感的 3 到 6 个变量。
2. 再判断哪些是公司硬事件，哪些是行业中观变量，哪些是全球触发因素。
2.5. 如果公司有多个业务线，先判断哪一条是“主利润线/主估值线”，行业 query 优先服务这条主线。
3. 公司层 query 优先覆盖：业绩、订单/项目、资本运作、监管/风险、重大经营变化。
4. 行业层 query 优先覆盖：政策、供给、需求、价格/景气、库存/资本开支、竞争格局/技术进展中的多个变量。
5. 全球层 query 优先覆盖：全球触发因素 + 资产/商品词 + 传导变量词。
6. 最后检查 query 是否像“金融资讯搜索词串”，而不是研究报告句子或自然语言问题。
7. 最后再检查：是否因为贪多而把太多产品线/船型/赛道揉成一条 query；如果是，删掉弱相关项，只保留主线。

以下是高质量 few-shot 示例，请模仿其风格与粒度：
{QUERY_PLANNER_FEW_SHOTS}

输出要求：
- 只输出 JSON
- 不要输出 Markdown
- JSON 必须严格符合下面的结构

{json.dumps(QUERY_PLANNER_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}
""".strip()


def _compact_list(values: Any, limit: int = 6) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _build_context_summary(company_context: dict[str, Any]) -> dict[str, Any]:
    classification = company_context.get("classification") or {}
    business = company_context.get("business_context") or {}
    search = company_context.get("search_context") or {}

    summary = {
        "classification": {
            "industry": classification.get("industry") or "",
            "company_type": classification.get("company_type") or "",
        },
        "business": {
            "sub_industry": business.get("sub_industry") or "",
            "business_model": business.get("business_model") or "",
            "company_intro": str(business.get("company_intro") or "")[:180],
            "core_products": _compact_list(business.get("core_products"), limit=5),
            "main_business_items": _compact_list(business.get("main_business_items"), limit=6),
        },
        "search": {
            "search_aliases": _compact_list(search.get("search_aliases"), limit=8),
            "ths_concepts": _compact_list(search.get("ths_concepts"), limit=8),
            "index_memberships": _compact_list(search.get("index_memberships"), limit=6),
            "seed_titles": _compact_list(search.get("seed_titles"), limit=4),
        },
    }
    return summary


def build_query_planner_user_prompt(context: dict[str, Any]) -> str:
    company_context = context.get("company_context") or {}
    context_summary = _build_context_summary(company_context)
    return (
        "请根据以下公司信息生成事件检索 query。\n"
        f"股票代码: {context['ticker']}\n"
        f"公司名称: {context['company_name']}\n"
        f"分析日期: {context['analysis_date']}\n"
        f"所属行业: {context['industry']}\n"
        f"公司类型: {context['company_type']}\n"
        "系统压缩后的最小上下文如下，请优先使用公司介绍和所属板块来缩窄赛道语义：\n"
        f"{json.dumps(context_summary, ensure_ascii=False, indent=2)}\n"
        "请特别思考：哪些变量最可能影响该公司，哪些行业事件最值得跟踪，哪些全球事件可能通过价格、供给、需求、运输、政策或风险偏好传导到该公司。\n"
        "如果粗行业标签过宽，请优先利用 business.sub_industry、business_model、company_intro、core_products、main_business_items，以及 search.ths_concepts、search.index_memberships 推断更贴近资讯检索语境的细分赛道。\n"
        "如果最小上下文给出了主营业务、板块概念或核心产品，请优先使用这些更具体的名词，而不要停留在过宽的行业标签上。\n"
        "如果公司是多业务组合，请先判断哪条业务线最影响利润和估值；行业 query 不要把 3 个以上子赛道混在一起，优先主线，最多补 1 个强相关次主线。\n"
        "如果你识别到行业存在原生指标或原生术语，请优先把这些词写进 query，例如航运里的 VLCC/AFRAMAX/BDTI/TCE，资源品里的具体商品价格/库存/加工费，半导体设备里的资本开支/先进封装/国产替代。\n"
        "请优先生成像示例那样的‘金融资讯搜索词串’，避免写成长句分析。\n"
        "每层只输出 1 条最高质量 query。只输出 JSON。\n"
    )


class EventQueryPlanner:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or DEFAULT_CONFIG.copy()

        llm_kwargs: dict[str, Any] = {"project_dir": self.config.get("project_dir")}
        if self.config.get("llm_provider") == "openai" and self.config.get("openai_reasoning_effort"):
            llm_kwargs["reasoning_effort"] = self.config.get("openai_reasoning_effort")
        if self.config.get("llm_provider") == "google" and self.config.get("google_thinking_level"):
            llm_kwargs["thinking_level"] = self.config.get("google_thinking_level")
        if self.config.get("llm_provider") in ("bailian", "dashscope") and self.config.get("bailian_api_key"):
            llm_kwargs["api_key"] = self.config.get("bailian_api_key")
        if self.config.get("llm_provider") in ("bailian", "dashscope"):
            llm_kwargs["bailian_enable_thinking"] = self.config.get("event_query_planner_enable_thinking", True)
            thinking_budget = self.config.get("event_query_planner_thinking_budget")
            if thinking_budget is None:
                thinking_budget = self.config.get("bailian_thinking_budget")
            if thinking_budget is not None:
                llm_kwargs["bailian_thinking_budget"] = thinking_budget

        llm_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config.get("deep_think_llm", "qwen3.5-plus"),
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        self.llm = llm_client.get_llm()

    def plan(self, context: dict[str, Any]) -> dict[str, Any]:
        messages = [
            SystemMessage(content=QUERY_PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=build_query_planner_user_prompt(context)),
        ]
        response = self.llm.invoke(messages)
        return self._parse_json(response.content)

    def _parse_json(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError(f"EventQueryPlanner did not return valid JSON:\n{text}")
            parsed = json.loads(text[start : end + 1])

        normalized = json.loads(json.dumps(QUERY_PLANNER_OUTPUT_TEMPLATE, ensure_ascii=False))
        value = parsed.get("sensitivity_variables", [])
        if isinstance(value, list):
            normalized["sensitivity_variables"] = [str(item).strip() for item in value if str(item).strip()]
        for key in ("company_query", "industry_query", "global_event_query"):
            normalized[key] = str(parsed.get(key, "")).strip()
        rationale = parsed.get("query_rationale", {})
        if isinstance(rationale, dict):
            normalized["query_rationale"].update(
                {
                    "company": str(rationale.get("company", "")).strip(),
                    "industry": str(rationale.get("industry", "")).strip(),
                    "global": str(rationale.get("global", "")).strip(),
                }
            )
        return normalized
