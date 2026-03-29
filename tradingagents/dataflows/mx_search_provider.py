from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests

from .config import get_config


MX_SEARCH_API_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/news-search"


def _load_project_mx_api_key(project_dir: str | None) -> str | None:
    if not project_dir:
        return None

    config_path = Path(project_dir).parent / "config" / "mx_search.toml"
    if not config_path.exists():
        return None

    content = config_path.read_text(encoding="utf-8")
    match = re.search(r'^\s*api_key\s*=\s*["\']([^"\']+)["\']\s*$', content, flags=re.MULTILINE)
    if not match:
        return None

    api_key = match.group(1).strip()
    return api_key or None


def _require_mx_api_key() -> str:
    config = get_config()
    api_key = (
        config.get("mx_api_key")
        or _load_project_mx_api_key(config.get("project_dir"))
        or os.environ.get("MX_APIKEY")
    )
    if not api_key:
        raise RuntimeError(
            "Missing MX Search API key. Set config/mx_search.toml, config['mx_api_key'], or MX_APIKEY."
        )
    return api_key


def _extract_candidate_items(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "title" in node or "trunk" in node:
                items.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return items


def _normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    secu_list = item.get("secuList") or []
    normalized_secu_list: list[dict[str, Any]] = []
    for secu in secu_list:
        if not isinstance(secu, dict):
            continue
        normalized_secu_list.append(
            {
                "secu_code": secu.get("secuCode"),
                "secu_name": secu.get("secuName"),
                "secu_type": secu.get("secuType"),
            }
        )

    trunk = item.get("trunk")
    if isinstance(trunk, (dict, list)):
        trunk_text = json.dumps(trunk, ensure_ascii=False)
    else:
        trunk_text = "" if trunk is None else str(trunk)

    return {
        "title": item.get("title", ""),
        "trunk": trunk_text,
        "secu_list": normalized_secu_list,
    }


def _text_contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords if keyword)


def _rerank_company_results(
    results: list[dict[str, Any]],
    ticker: str,
    company_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    strong_keywords = [
        "业绩", "预增", "预减", "快报", "年报", "季报", "一季报", "半年报",
        "中标", "订单", "合同", "回购", "增持", "减持", "质押", "收购", "并购",
        "重组", "产能", "扩产", "停产", "诉讼", "处罚", "监管", "问询", "解禁",
        "募投", "分红", "激励", "新品", "客户", "涨价", "降价", "AI", "CPO",
    ]
    weak_keywords = [
        "浮亏", "基金重仓", "盘前要闻", "ETF", "选哪个", "概念股", "收评", "午评", "龙虎榜复盘",
    ]
    company_aliases = [ticker, ticker.split(".")[0], company_name]

    scored: list[tuple[int, dict[str, Any]]] = []
    for item in results:
        title = item.get("title", "") or ""
        trunk = item.get("trunk", "") or ""
        text = f"{title} {trunk}"
        score = 0
        if _text_contains_any(text, company_aliases):
            score += 5
        if _text_contains_any(text, strong_keywords):
            score += 4
        if "公告" in title:
            score += 2
        if "研报" in title:
            score += 1
        if _text_contains_any(text, weak_keywords):
            score -= 4
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [item for _, item in scored[:limit]]
    if ranked:
        return ranked
    return results[:limit]


def _rerank_macro_results(
    results: list[dict[str, Any]],
    industry: str,
    limit: int,
) -> list[dict[str, Any]]:
    strong_keywords = [
        "政策", "规划", "产业", "景气", "涨价", "降价", "供给", "需求", "出口", "进口",
        "补贴", "关税", "算力", "AI", "光通信", "5G", "6G", "资本开支", "景气度",
        "价格", "周期", "创新高", "刷新纪录", "爆发", "预期",
    ]
    weak_keywords = [
        "盘前要闻", "ETF", "选哪个", "周报", "收评", "午评", "快讯汇总",
    ]
    industry_aliases = [industry] if industry else []

    scored: list[tuple[int, dict[str, Any]]] = []
    for item in results:
        title = item.get("title", "") or ""
        trunk = item.get("trunk", "") or ""
        text = f"{title} {trunk}"
        score = 0
        if _text_contains_any(text, industry_aliases):
            score += 4
        if _text_contains_any(text, strong_keywords):
            score += 3
        if _text_contains_any(text, weak_keywords):
            score -= 3
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [item for _, item in scored[:limit]]
    if ranked:
        return ranked
    return results[:limit]


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in results:
        key = ((item.get("title") or "").strip(), (item.get("trunk") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _multi_query_search(queries: list[str], limit_per_query: int = 12) -> dict[str, Any]:
    query_results: list[dict[str, Any]] = []
    merged_results: list[dict[str, Any]] = []
    for query in queries:
        payload = mx_search(query, limit=limit_per_query)
        results = payload.get("results", [])
        query_results.append(
            {
                "query": query,
                "results_count": len(results),
                "results": results,
            }
        )
        merged_results.extend(results)
    return {
        "queries": queries,
        "query_results": query_results,
        "results": _dedupe_results(merged_results),
    }


def mx_search(query: str, limit: int = 10) -> dict[str, Any]:
    api_key = _require_mx_api_key()
    response = requests.post(
        MX_SEARCH_API_URL,
        headers={
            "Content-Type": "application/json",
            "apikey": api_key,
        },
        json={"query": query},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    candidates = _extract_candidate_items(payload)
    results = []
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        normalized = _normalize_result(item)
        dedupe_key = (normalized["title"], normalized["trunk"])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        if not normalized["title"] and not normalized["trunk"]:
            continue
        results.append(normalized)
        if len(results) >= limit:
            break

    return {
        "query": query,
        "results": results,
        "raw": payload,
    }


def get_mx_search_news(ticker: str, start_date: str, end_date: str) -> str:
    query = f"{ticker} {start_date}到{end_date} 相关新闻 研报 公告 事件"
    return json.dumps(mx_search(query, limit=12), ensure_ascii=False)


def get_mx_search_global_news(curr_date: str, look_back_days: int = 7, limit: int = 8) -> str:
    query = f"{curr_date}前{look_back_days}天 A股 宏观 政策 行业 重要资讯"
    return json.dumps(mx_search(query, limit=limit), ensure_ascii=False)


def search_mx_company_event_news(ticker: str, company_name: str, analysis_date: str, look_back_days: int = 30, limit: int = 10) -> dict[str, Any]:
    company_ref = company_name or ticker
    queries = [
        f"{company_ref} {ticker} {analysis_date}前{look_back_days}天 业绩 预告 快报 年报 季报",
        f"{company_ref} {ticker} {analysis_date}前{look_back_days}天 订单 合同 中标 客户 扩产 产能",
        f"{company_ref} {ticker} {analysis_date}前{look_back_days}天 回购 增持 减持 并购 重组 定增 H股",
        f"{company_ref} {ticker} {analysis_date}前{look_back_days}天 监管 问询 处罚 诉讼 风险 公告",
        f"{company_ref} {ticker} {analysis_date}前{look_back_days}天 研报 AI CPO 光模块 核心业务",
    ]
    raw = _multi_query_search(queries, limit_per_query=max(limit * 2, 10))
    raw["query"] = " || ".join(queries)
    deduped_results = raw.get("results", [])
    raw["deduped_results_count"] = len(deduped_results)
    raw["results"] = _rerank_company_results(deduped_results, ticker=ticker, company_name=company_name, limit=limit)
    raw["reranked_results_count"] = len(raw["results"])
    return raw


def search_mx_macro_event_news(industry: str, analysis_date: str, look_back_days: int = 10, limit: int = 10) -> dict[str, Any]:
    industry_ref = industry or "相关行业"
    queries = [
        f"A股 {industry_ref} {analysis_date}前{look_back_days}天 行业 政策 规划 补贴 监管",
        f"A股 {industry_ref} {analysis_date}前{look_back_days}天 景气度 需求 供给 价格 周期",
        f"A股 {industry_ref} {analysis_date}前{look_back_days}天 技术突破 AI 算力 光通信 资本开支",
        f"A股 {industry_ref} {analysis_date}前{look_back_days}天 龙头 公司 业绩 前瞻 产业链",
    ]
    raw = _multi_query_search(queries, limit_per_query=max(limit * 2, 10))
    raw["query"] = " || ".join(queries)
    deduped_results = raw.get("results", [])
    raw["deduped_results_count"] = len(deduped_results)
    raw["results"] = _rerank_macro_results(deduped_results, industry=industry, limit=limit)
    raw["reranked_results_count"] = len(raw["results"])
    return raw


def search_mx_queries(
    queries: list[str],
    limit_per_query: int = 12,
    rerank_mode: str = "generic",
    ticker: str = "",
    company_name: str = "",
    industry: str = "",
    final_limit: int = 10,
) -> dict[str, Any]:
    raw = _multi_query_search(queries, limit_per_query=limit_per_query)
    deduped_results = raw.get("results", [])
    raw["deduped_results_count"] = len(deduped_results)
    if rerank_mode == "company":
        raw["results"] = _rerank_company_results(
            deduped_results,
            ticker=ticker,
            company_name=company_name,
            limit=final_limit,
        )
    elif rerank_mode == "macro":
        raw["results"] = _rerank_macro_results(
            deduped_results,
            industry=industry,
            limit=final_limit,
        )
    else:
        raw["results"] = deduped_results[:final_limit]
    raw["reranked_results_count"] = len(raw["results"])
    return raw


def search_mx_custom_event_news(query: str, limit: int = 10) -> dict[str, Any]:
    return mx_search(query, limit=limit)
