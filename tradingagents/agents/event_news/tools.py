from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.event_news_bundle_service import (
    get_company_event_news as _get_company_event_news,
    get_macro_policy_news as _get_macro_policy_news,
    search_custom_event_news as _search_custom_event_news,
)


@tool
def get_company_event_news(
    ticker: Annotated[str, "A股ts_code，例如300394.SZ"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充公司相关新闻、研报与事件线索。"""
    return json.dumps(_get_company_event_news(ticker, analysis_date), ensure_ascii=False)


@tool
def get_macro_policy_news(
    ticker: Annotated[str, "A股ts_code，例如300394.SZ"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充行业、政策与宏观事件线索。"""
    return json.dumps(_get_macro_policy_news(ticker, analysis_date), ensure_ascii=False)


@tool
def search_custom_event_news(
    query: Annotated[str, "自定义事件检索问句"],
    limit: Annotated[int, "返回结果数量上限"] = 10,
) -> str:
    """按自定义问句补充金融资讯与事件证据。"""
    return json.dumps(_search_custom_event_news(query, limit), ensure_ascii=False)


EVENT_NEWS_TOOLS = [
    get_company_event_news,
    get_macro_policy_news,
    search_custom_event_news,
]
