from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import re
import time
from typing import Any

from tradingagents.dataflows.config import get_config
from .company_context_service import build_company_context
from .mx_search_provider import (
    search_mx_queries,
    search_mx_custom_event_news,
)
from .tushare_provider import _normalize_symbol, _read_or_query, _require_tushare


COMPANY_DIMENSIONS = {
    "earnings": ["业绩", "预告", "快报", "年报", "季报", "一季报", "半年报", "净利", "营收", "利润"],
    "orders_projects": ["订单", "合同", "中标", "项目", "复产", "投产", "扩产", "产能", "项目进展", "签约"],
    "capital_markets": ["回购", "增持", "减持", "定增", "发债", "融资", "贷款", "担保", "股权", "并购", "重组"],
    "regulatory_risk": ["监管", "问询", "处罚", "诉讼", "违约", "风险", "工作函", "立案", "调查"],
    "operations": ["停产", "复工", "交付", "客户", "新品", "认证", "量产"],
}

INDUSTRY_DIMENSIONS = {
    "policy": ["政策", "规划", "补贴", "监管", "关税", "牌照", "规则", "集采"],
    "supply": ["供给", "产量", "产能", "开工率", "停产", "检修", "扩产", "限产", "增产"],
    "demand": ["需求", "订单", "销量", "装机", "渗透率", "消费", "出货"],
    "price_cycle": ["价格", "油价", "煤价", "铜价", "金价", "价差", "景气", "景气度", "周期"],
    "capex_inventory": ["资本开支", "capex", "库存", "补库", "去库", "勘探开发"],
    "technology_competition": ["技术", "突破", "升级", "算力", "光通信", "芯片", "国产替代", "竞争格局"],
}

GLOBAL_TRIGGER_DIMENSIONS = {
    "geopolitics": ["霍尔木兹", "红海", "中东", "地缘", "冲突", "封锁", "战争", "制裁"],
    "commodity": ["原油", "油价", "天然气", "铜价", "金价", "煤价", "大宗商品"],
    "macro_policy": ["opec", "美联储", "美元指数", "汇率", "利率", "关税", "贸易政策"],
    "logistics": ["航运", "运价", "保险", "港口", "物流", "海运"],
}

GLOBAL_TRANSMISSION_DIMENSIONS = {
    "supply_demand": ["供给", "需求", "产量", "库存", "进口", "出口", "补库", "去库", "断供"],
    "cost_margin": ["成本", "毛利", "利润", "价差", "战争险", "保险"],
    "pricing": ["价格", "油价", "运价", "汇率", "利率"],
    "investment": ["资本开支", "capex", "勘探开发", "扩产", "开工率"],
    "risk_appetite": ["风险偏好", "避险", "估值", "风险溢价"],
}


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords if keyword)


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def _matched_dimensions(text: str, dimension_map: dict[str, list[str]]) -> dict[str, list[str]]:
    matched: dict[str, list[str]] = {}
    for name, keywords in dimension_map.items():
        hits = _matched_keywords(text, keywords)
        if hits:
            matched[name] = hits
    return matched


def _infer_direction(text: str) -> str:
    bullish_keywords = ["预增", "中标", "签约", "复产", "投产", "上涨", "上调", "突破", "扩产", "回购", "增持"]
    bearish_keywords = ["预降", "停产", "问询", "处罚", "诉讼", "违约", "下调", "暴跌", "封锁", "冲突", "风险"]
    bullish = len(_matched_keywords(text, bullish_keywords))
    bearish = len(_matched_keywords(text, bearish_keywords))
    if bullish > bearish:
        return "bullish"
    if bearish > bullish:
        return "bearish"
    return "neutral"


def _infer_time_horizon(text: str) -> str:
    if _contains_any(text, ["最近", "短期", "日内", "周报", "一季度", "季度"]):
        return "short_term"
    if _contains_any(text, ["年度", "年报", "资本开支", "扩产", "规划", "产能"]):
        return "medium_term"
    return "medium_term"


def _title_signature(title: str) -> str:
    signature = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+", " ", title).strip()
    signature = re.sub(r"\s+", " ", signature)
    return signature[:48].lower()


def _normalize_layer_events(layer: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: dict[str, dict[str, Any]] = {}
    for item in results:
        title = str(item.get("title", "") or "").strip()
        trunk = str(item.get("trunk", "") or "").strip()
        text = f"{title} {trunk}"
        if layer == "company":
            dimensions = _matched_dimensions(text, COMPANY_DIMENSIONS)
            key_base = sorted(dimensions.keys())[:2] or [_title_signature(title)]
            event_type = (
                "earnings" if "earnings" in dimensions else
                "order" if "orders_projects" in dimensions else
                "mna" if "capital_markets" in dimensions else
                "regulation" if "regulatory_risk" in dimensions else
                "capacity" if "operations" in dimensions else
                "other"
            )
            affected = sorted(dimensions.keys())
        elif layer == "industry":
            dimensions = _matched_dimensions(text, INDUSTRY_DIMENSIONS)
            key_base = sorted(dimensions.keys())[:2] or [_title_signature(title)]
            event_type = (
                "policy" if "policy" in dimensions else
                "industry_cycle" if any(key in dimensions for key in ("supply", "demand", "price_cycle", "capex_inventory")) else
                "commodity" if "price_cycle" in dimensions else
                "other"
            )
            affected = sorted(dimensions.keys())
        else:
            trigger_dims = _matched_dimensions(text, GLOBAL_TRIGGER_DIMENSIONS)
            transmission_dims = _matched_dimensions(text, GLOBAL_TRANSMISSION_DIMENSIONS)
            dimensions = {"trigger": sorted(trigger_dims.keys()), "transmission": sorted(transmission_dims.keys())}
            key_base = sorted(trigger_dims.keys())[:2] + sorted(transmission_dims.keys())[:1]
            if not key_base:
                key_base = [_title_signature(title)]
            event_type = (
                "geopolitics" if "geopolitics" in trigger_dims else
                "commodity" if "commodity" in trigger_dims else
                "liquidity" if "macro_policy" in trigger_dims else
                "other"
            )
            affected = sorted(set(trigger_dims.keys()) | set(transmission_dims.keys()))

        cluster_key = f"{layer}:{'|'.join(key_base)}"
        cluster = clusters.setdefault(
            cluster_key,
            {
                "event_key": cluster_key,
                "layer": layer,
                "event_type": event_type,
                "title": title,
                "direction": _infer_direction(text),
                "importance": 0.0,
                "time_horizon": _infer_time_horizon(text),
                "affected_variables": affected,
                "dimensions": dimensions,
                "evidence_titles": [],
                "evidence_items": [],
                "summary": "",
            },
        )
        cluster["evidence_titles"].append(title)
        cluster["evidence_items"].append(item)

    normalized: list[dict[str, Any]] = []
    for cluster in clusters.values():
        evidence_count = len(cluster["evidence_titles"])
        cluster["importance"] = round(min(1.0, 0.35 + evidence_count * 0.15 + len(cluster["affected_variables"]) * 0.08), 2)
        if cluster["layer"] == "company":
            cluster["summary"] = f"公司层事件聚焦于{ '、'.join(cluster['affected_variables'][:3]) or '经营变化'}，共聚合 {evidence_count} 条证据。"
        elif cluster["layer"] == "industry":
            cluster["summary"] = f"行业层事件聚焦于{ '、'.join(cluster['affected_variables'][:3]) or '景气变化'}，共聚合 {evidence_count} 条证据。"
        else:
            cluster["summary"] = f"全球层事件聚焦于{ '、'.join(cluster['affected_variables'][:3]) or '外部冲击'}，共聚合 {evidence_count} 条证据。"
        normalized.append(cluster)

    normalized.sort(key=lambda item: (item["importance"], len(item["evidence_titles"])), reverse=True)
    return normalized


def _build_event_chain(
    company_events: list[dict[str, Any]],
    industry_events: list[dict[str, Any]],
    global_events: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]] | list[str]]:
    global_triggers = [
        {
            "title": event["title"],
            "event_type": event["event_type"],
            "affected_variables": event["affected_variables"],
            "summary": event["summary"],
        }
        for event in global_events[:3]
    ]
    industry_variables = [
        {
            "title": event["title"],
            "event_type": event["event_type"],
            "affected_variables": event["affected_variables"],
            "summary": event["summary"],
        }
        for event in industry_events[:3]
    ]
    company_impacts = [
        {
            "title": event["title"],
            "event_type": event["event_type"],
            "affected_variables": event["affected_variables"],
            "summary": event["summary"],
        }
        for event in company_events[:3]
    ]

    missing_links: list[str] = []
    if not global_triggers:
        missing_links.append("缺全球触发事件证据")
    if not industry_variables:
        missing_links.append("缺行业中观变量证据")
    if not company_impacts:
        missing_links.append("缺公司层经营或风险兑现证据")
    if global_triggers and not any(item["affected_variables"] for item in global_triggers):
        missing_links.append("全球层缺传导变量")
    return {
        "global_triggers": global_triggers,
        "industry_variables": industry_variables,
        "company_impacts": company_impacts,
        "missing_links": missing_links,
    }


def _fetch_stock_basic(ts_code: str) -> dict[str, Any]:
    pro = _require_tushare()
    basic = _read_or_query("stock_basic", {"ts_code": ts_code}, lambda: pro.stock_basic(ts_code=ts_code))
    if basic.empty:
        return {}
    row = basic.head(1).iloc[0]
    return {
        "name": row.get("name"),
        "industry": row.get("industry"),
        "market": row.get("market"),
        "list_date": row.get("list_date"),
    }


def _build_event_compact_signals(company_news_count: int, macro_news_count: int) -> dict[str, str]:
    total = company_news_count + macro_news_count
    if total >= 14:
        density = "high"
    elif total >= 6:
        density = "medium"
    else:
        density = "low"

    return {
        "company_event_bias": "unknown",
        "macro_event_bias": "unknown",
        "event_density": density,
        "policy_sensitivity": "medium",
        "earnings_catalyst_state": "unknown",
        "risk_event_level": "unknown",
    }


def _enrich_event_compact_signals(
    signals: dict[str, str],
    company_events: list[dict[str, Any]],
    industry_events: list[dict[str, Any]],
    global_events: list[dict[str, Any]],
) -> dict[str, str]:
    company_bias = "none"
    if any(event["direction"] == "bullish" for event in company_events):
        company_bias = "positive"
    if any(event["direction"] == "bearish" for event in company_events):
        company_bias = "mixed" if company_bias == "positive" else "negative"

    macro_bias = "none"
    macro_events = industry_events + global_events
    if any(event["direction"] == "bullish" for event in macro_events):
        macro_bias = "positive"
    if any(event["direction"] == "bearish" for event in macro_events):
        macro_bias = "mixed" if macro_bias == "positive" else "negative"

    policy_sensitivity = "high" if any("policy" in event.get("affected_variables", []) for event in industry_events) else "medium"
    earnings_state = "confirmed_positive" if any(event["event_type"] == "earnings" and event["direction"] == "bullish" for event in company_events) else "none"
    if any(event["event_type"] == "earnings" and event["direction"] == "bearish" for event in company_events):
        earnings_state = "confirmed_negative"
    risk_level = "high" if any(event["event_type"] in {"regulation", "geopolitics"} or event["direction"] == "bearish" for event in macro_events + company_events) else "medium"

    enriched = dict(signals)
    enriched.update(
        {
            "company_event_bias": company_bias,
            "macro_event_bias": macro_bias,
            "policy_sensitivity": policy_sensitivity,
            "earnings_catalyst_state": earnings_state,
            "risk_event_level": risk_level,
        }
    )
    return enriched


def _build_event_context_snapshot(
    company_events: list[dict[str, Any]],
    industry_events: list[dict[str, Any]],
    global_events: list[dict[str, Any]],
    event_chain: dict[str, Any],
    compact_signals: dict[str, str],
) -> dict[str, str]:
    def strength(events: list[dict[str, Any]]) -> str:
        if len(events) >= 3:
            return "strong"
        if len(events) >= 1:
            return "moderate"
        return "weak"

    missing_count = len(event_chain.get("missing_links", []))
    if missing_count == 0:
        chain_completeness = "complete"
    elif missing_count == 1:
        chain_completeness = "partial"
    else:
        chain_completeness = "broken"

    dominant_driver_layer = "company"
    layer_sizes = {
        "company": len(company_events),
        "industry": len(industry_events),
        "global": len(global_events),
    }
    dominant_driver_layer = max(layer_sizes, key=layer_sizes.get)

    dominant_driver_type = "event"
    if dominant_driver_layer == "industry" and industry_events:
        dominant_driver_type = industry_events[0].get("event_type", "event")
    elif dominant_driver_layer == "global" and global_events:
        dominant_driver_type = global_events[0].get("event_type", "event")
    elif company_events:
        dominant_driver_type = company_events[0].get("event_type", "event")

    bullish_variables = []
    bearish_variables = []
    actionable_catalyst = ""
    critical_risk = ""

    for event in company_events + industry_events + global_events:
        affected = event.get("affected_variables", [])
        if event.get("direction") == "bullish":
            bullish_variables.extend(affected)
            if not actionable_catalyst:
                actionable_catalyst = event.get("title", "")
        elif event.get("direction") == "bearish":
            bearish_variables.extend(affected)
            if not critical_risk:
                critical_risk = event.get("title", "")

    if not actionable_catalyst:
        actionable_catalyst = (company_events or industry_events or global_events or [{}])[0].get("title", "")
    if not critical_risk:
        critical_risk = event_chain.get("missing_links", [""])[0] if event_chain.get("missing_links") else ""

    return {
        "company_event_strength": strength(company_events),
        "industry_context_strength": strength(industry_events),
        "global_context_strength": strength(global_events),
        "chain_completeness": chain_completeness,
        "dominant_driver_layer": dominant_driver_layer,
        "dominant_driver_type": dominant_driver_type,
        "primary_bullish_variable": bullish_variables[0] if bullish_variables else compact_signals.get("company_event_bias", ""),
        "primary_bearish_variable": bearish_variables[0] if bearish_variables else compact_signals.get("risk_event_level", ""),
        "most_actionable_catalyst": actionable_catalyst,
        "most_critical_risk": critical_risk,
    }


def _fallback_global_query(industry: str, company_type: str) -> str:
    if company_type == "cyclical_resources":
        if industry in {"石油开采", "石油加工", "石油贸易"}:
            return "全球 原油 霍尔木兹海峡 OPEC 油价 航运 供给 运价 最近10天"
        if industry in {"铜", "铝", "黄金", "小金属", "铅锌"}:
            return f"全球 {industry} 价格 库存 供给 关税 美元指数 最近10天"
        return f"全球 大宗商品 {industry} 价格 供给 需求 库存 最近10天"
    if company_type == "tmt_growth":
        return "全球 AI 算力 芯片 光通信 资本开支 出口限制 最近10天"
    if company_type == "financials":
        return "全球 利率 美元指数 汇率 监管 风险偏好 最近10天"
    return f"全球 {industry} 政策 价格 供给 需求 风险 最近10天"


def _search_with_retry(
    *,
    layer: str,
    queries: list[str],
    limit_per_query: int,
    rerank_mode: str,
    ticker: str = "",
    company_name: str = "",
    industry: str = "",
    final_limit: int = 10,
    max_attempts: int = 3,
    retry_backoff_seconds: float = 0.5,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] = {
        "queries": queries,
        "query_results": [],
        "results": [],
        "deduped_results_count": 0,
        "reranked_results_count": 0,
    }

    for attempt in range(1, max_attempts + 1):
        result = search_mx_queries(
            queries,
            limit_per_query=limit_per_query,
            rerank_mode=rerank_mode,
            ticker=ticker,
            company_name=company_name,
            industry=industry,
            final_limit=final_limit,
        )
        query_results = result.get("query_results", [])
        raw_total = sum(int(item.get("results_count", 0)) for item in query_results)
        deduped = int(result.get("deduped_results_count", 0))
        reranked = int(result.get("reranked_results_count", 0))
        attempts.append(
            {
                "attempt": attempt,
                "layer": layer,
                "queries": list(queries),
                "raw_results_count": raw_total,
                "deduped_results_count": deduped,
                "reranked_results_count": reranked,
                "query_results": query_results,
            }
        )
        last_result = result
        if deduped > 0:
            break
        if attempt < max_attempts:
            time.sleep(retry_backoff_seconds * attempt)

    enriched = dict(last_result)
    enriched["retry_attempts"] = attempts
    enriched["retry_used"] = len(attempts) > 1
    enriched["final_attempt"] = attempts[-1]["attempt"] if attempts else 1
    return enriched


def _run_parallel_searches(
    ts_code: str,
    company_name: str,
    industry: str,
    company_query: str,
    industry_query: str,
    global_query: str,
    company_news_limit: int,
    macro_news_limit: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=3) as executor:
        company_future = executor.submit(
            _search_with_retry,
            layer="company",
            queries=[company_query] if company_query else [],
            limit_per_query=max(company_news_limit * 2, 10),
            rerank_mode="company",
            ticker=ts_code,
            company_name=company_name,
            final_limit=company_news_limit,
        )
        industry_future = executor.submit(
            _search_with_retry,
            layer="industry",
            queries=[industry_query] if industry_query else [],
            limit_per_query=max(macro_news_limit * 2, 10),
            rerank_mode="macro",
            industry=industry,
            final_limit=macro_news_limit,
        )
        global_future = executor.submit(
            _search_with_retry,
            layer="global",
            queries=[global_query] if global_query else [],
            limit_per_query=max(macro_news_limit * 2, 10),
            rerank_mode="global",
            final_limit=macro_news_limit,
        )

        return company_future.result(), industry_future.result(), global_future.result()


def build_event_news_data_bundle(
    ticker: str,
    analysis_date: str,
    company_news_limit: int = 8,
    macro_news_limit: int = 8,
    company_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from tradingagents.agents.event_news.query_planner import EventQueryPlanner

    ts_code = _normalize_symbol(ticker)
    requested_date = datetime.strptime(analysis_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    effective_date = requested_date

    company_context = company_context or build_company_context(
        ticker=ts_code,
        analysis_date=analysis_date,
        date_mode="natural_day",
    )
    meta = {
        "name": company_context.get("identity", {}).get("company_name") or ts_code,
        "industry": company_context.get("classification", {}).get("industry") or "",
        "market": company_context.get("identity", {}).get("market") or "",
        "list_date": "",
    }
    company_type = company_context.get("classification", {}).get("company_type") or "general_corporate"

    planner = EventQueryPlanner(config=get_config())
    planner_context = {
        "ticker": ts_code,
        "company_name": meta.get("name") or ts_code,
        "analysis_date": effective_date,
        "industry": meta.get("industry") or "",
        "company_type": company_type,
        "business_hint": None,
        "company_context": company_context,
    }
    query_plan = planner.plan(planner_context)

    company_query = query_plan.get("company_query", "")
    industry_query = query_plan.get("industry_query", "")
    global_query = query_plan.get("global_event_query", "") or _fallback_global_query(
        industry=meta.get("industry") or "",
        company_type=company_type,
    )

    company_news, industry_news, global_news = _run_parallel_searches(
        ts_code=ts_code,
        company_name=meta.get("name") or ts_code,
        industry=meta.get("industry") or "",
        company_query=company_query,
        industry_query=industry_query,
        global_query=global_query,
        company_news_limit=company_news_limit,
        macro_news_limit=macro_news_limit,
    )
    macro_news_results = []
    for group in (industry_news.get("results", []), global_news.get("results", [])):
        for item in group:
            if item not in macro_news_results:
                macro_news_results.append(item)
    macro_news_results = macro_news_results[:macro_news_limit]
    normalized_company_events = _normalize_layer_events("company", company_news.get("results", []))
    normalized_industry_events = _normalize_layer_events("industry", industry_news.get("results", []))
    normalized_global_events = _normalize_layer_events("global", global_news.get("results", []))
    event_chain = _build_event_chain(
        company_events=normalized_company_events,
        industry_events=normalized_industry_events,
        global_events=normalized_global_events,
    )
    event_compact_signals = _enrich_event_compact_signals(
        _build_event_compact_signals(
            company_news_count=len(company_news.get("results", [])),
            macro_news_count=len(macro_news_results),
        ),
        company_events=normalized_company_events,
        industry_events=normalized_industry_events,
        global_events=normalized_global_events,
    )
    event_context_snapshot = _build_event_context_snapshot(
        company_events=normalized_company_events,
        industry_events=normalized_industry_events,
        global_events=normalized_global_events,
        event_chain=event_chain,
        compact_signals=event_compact_signals,
    )

    return {
        "ticker": ts_code,
        "requested_date": requested_date,
        "effective_trade_date": effective_date,
        "meta": meta,
        "company_context": company_context,
        "company_news": company_news.get("results", []),
        "macro_news": macro_news_results,
        "normalized_company_events": normalized_company_events,
        "normalized_industry_events": normalized_industry_events,
        "normalized_global_events": normalized_global_events,
        "event_chain": event_chain,
        "announcements": [],
        "market_events": [],
        "event_compact_signals": event_compact_signals,
        "event_context_snapshot": event_context_snapshot,
        "query_plan": query_plan,
        "debug_trace": {
            "planner_context": planner_context,
            "company_context": company_context,
            "query_plan": query_plan,
            "company_search": company_news,
            "industry_search": industry_news,
            "global_search": global_news,
            "normalized_company_events": normalized_company_events,
            "normalized_industry_events": normalized_industry_events,
            "normalized_global_events": normalized_global_events,
            "event_chain": event_chain,
            "event_context_snapshot": event_context_snapshot,
        },
        "data_quality": {
            "company_news_count": len(company_news.get("results", [])),
            "macro_news_count": len(macro_news_results),
            "announcements_count": 0,
            "market_events_count": 0,
            "source": "mx_search+tushare",
        },
    }


def get_company_event_news(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_event_news_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "company_news": bundle["company_news"],
    }


def get_macro_policy_news(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_event_news_data_bundle(ticker, analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "macro_news": bundle["macro_news"],
    }


def search_custom_event_news(query: str, limit: int = 10) -> dict[str, Any]:
    return search_mx_custom_event_news(query=query, limit=limit)
