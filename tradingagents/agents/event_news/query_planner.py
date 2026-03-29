from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client


QUERY_PLANNER_OUTPUT_TEMPLATE = {
    "sensitivity_variables": [],
    "company_queries": [],
    "industry_queries": [],
    "global_event_queries": [],
    "query_rationale": {
        "company": "",
        "industry": "",
        "global": "",
    },
}


QUERY_PLANNER_SYSTEM_PROMPT = f"""
你是一个A股事件检索查询规划器。

你的任务不是分析新闻，也不是给出投资建议。你的唯一职责是：根据目标公司信息，生成一组高质量的金融资讯检索 query，用于后续的事件与新闻搜索。

你必须生成三层 query：
1. 公司层 query：用于检索该公司的直接相关新闻、公告、研报、业绩、订单、资本运作、监管与风险事件
2. 行业层 query：用于检索该公司所属行业的景气度、政策、供需、价格、技术进展和产业链变化
3. 全球事件层 query：用于检索可能影响该公司的国际事件、地缘风险、商品价格、运输、汇率、利率、政策变化等外部冲击

生成规则：
- query 必须适合中文金融资讯搜索，不要生成英文搜索引擎式 query
- query 必须尽量具体，围绕影响变量展开，而不是泛泛搜索最新新闻
- 优先关注能影响公司基本面、股价走势和行业景气度的事件
- 对周期股，要重点考虑商品价格、供需、运输、库存、政策和地缘因素
- 对成长股，要重点考虑需求、技术进展、资本开支、客户验证和监管政策
- 对金融股，要重点考虑监管、利率、资产质量和资本约束
- 不要生成重复 query
- 每个 query 保持简洁，尽量由公司名/股票代码/行业名 + 事件关键词构成
- 公司层输出4到6条，行业层输出3到5条，全球事件层输出3到5条
- 如果 business_hint 为空，不要臆造公司主营细节，基于股票名称、行业、公司类型和常见影响变量生成 query

输出要求：
- 只输出 JSON
- 不要输出 Markdown
- JSON 必须严格符合下面的结构

{json.dumps(QUERY_PLANNER_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}
""".strip()


def build_query_planner_user_prompt(context: dict[str, Any]) -> str:
    return (
        "请根据以下公司信息生成事件检索 query。\n"
        f"股票代码: {context['ticker']}\n"
        f"公司名称: {context['company_name']}\n"
        f"分析日期: {context['analysis_date']}\n"
        f"所属行业: {context['industry']}\n"
        f"公司类型: {context['company_type']}\n"
        f"业务提示: {context.get('business_hint')}\n"
        "请特别思考：哪些变量最可能影响该公司，哪些行业事件最值得跟踪，哪些全球事件可能通过价格、供给、需求、运输、政策或风险偏好传导到该公司。\n"
        "只输出 JSON。\n"
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
        for key in ("sensitivity_variables", "company_queries", "industry_queries", "global_event_queries"):
            value = parsed.get(key, [])
            if isinstance(value, list):
                normalized[key] = [str(item).strip() for item in value if str(item).strip()]
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
