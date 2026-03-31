from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.sector_flow_bundle_service import (
    get_sector_activity_context as _get_sector_activity_context,
    get_sector_peer_context as _get_sector_peer_context,
)


@tool
def get_sector_peer_context(
    ticker: Annotated[str, "A股ts_code，例如601872.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充个股在板块中的相对位置与同板块对比。"""
    return json.dumps(_get_sector_peer_context(ticker, analysis_date), ensure_ascii=False)


@tool
def get_sector_activity_context(
    ticker: Annotated[str, "A股ts_code，例如601872.SH"],
    analysis_date: Annotated[str, "分析日期，YYYY-MM-DD"],
) -> str:
    """补充板块活跃度、板块序列和紧密相关的资金面上下文。"""
    return json.dumps(_get_sector_activity_context(ticker, analysis_date), ensure_ascii=False)


SECTOR_FLOW_TOOLS = [
    get_sector_peer_context,
    get_sector_activity_context,
]
