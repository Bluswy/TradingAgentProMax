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


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword and keyword.lower() in lowered)


def _extract_query_keywords(queries: list[str], industry: str = "") -> list[str]:
    stopwords = {
        "近期", "最近", "最近10天", "最近30天", "行业", "公司", "相关", "影响", "变化",
        "供需", "景气", "政策", "需求", "供给", "价格", "成本", "库存", "技术", "进展",
        "竞争格局", "资本开支", "分析", "动态", "资讯", "新闻", "事件", "风险",
        "a股", "最新", "当前", "跟踪",
    }
    if industry:
        stopwords.add(industry.lower())
        stopwords.add(industry)

    keywords: list[str] = []
    seen: set[str] = set()
    for query in queries:
        for token in re.split(r"[\s,，/｜|]+", query):
            text = token.strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen or text in stopwords or lowered in stopwords:
                continue
            if len(text) <= 1 and not re.search(r"[A-Za-z0-9]{2,}", text):
                continue
            seen.add(lowered)
            keywords.append(text)
    return keywords


def _is_company_document_like(item: dict[str, Any], text: str) -> bool:
    secu_list = item.get("secu_list") or []
    if not secu_list:
        return False
    doc_keywords = [
        "公告", "年度报告", "年度报告摘要", "年报", "季报", "半年报", "净利",
        "营收", "分红", "回购", "减持", "增持", "募资", "问询函",
    ]
    return _text_contains_any(text, doc_keywords)


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
        "募投", "分红", "激励", "新品", "客户", "涨价", "降价", "项目", "签约",
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
        strong_hits = _count_keyword_hits(text, strong_keywords)
        if strong_hits:
            score += min(6, 2 + strong_hits)
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
    queries: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    strong_keywords = [
        "政策", "规划", "产业", "景气", "涨价", "降价", "供给", "需求", "出口", "进口",
        "补贴", "关税", "资本开支", "景气度", "价格", "周期", "创新高", "刷新纪录",
        "库存", "开工率", "产量", "产能", "竞争格局", "技术", "突破", "渗透率",
    ]
    sector_report_keywords = [
        "行业", "产业", "专题", "周报", "月报", "点评", "跟踪", "观察", "策略",
    ]
    weak_keywords = [
        "盘前要闻", "ETF", "选哪个", "周报", "收评", "午评", "快讯汇总",
    ]
    hard_exclude_keywords = [
        "募集说明书", "债券", "融资券", "超短期融资券", "公司债", "中期票据",
        "上会稿", "招股说明书", "募集书", "发行说明书",
    ]
    industry_aliases = [industry] if industry else []
    query_keywords = _extract_query_keywords(queries, industry=industry)
    core_variable_keywords = [
        "价格", "价差", "加工费", "库存", "开工率", "产量", "产能", "需求", "供给",
        "资本开支", "出口", "进口", "渗透率", "技术", "国产替代", "先进封装",
        "订单", "拆船", "交付", "运价", "tc", "rc", "tce", "bdti", "bdi",
    ]

    scored: list[tuple[int, dict[str, Any]]] = []
    for item in results:
        title = item.get("title", "") or ""
        trunk = item.get("trunk", "") or ""
        text = f"{title} {trunk}"
        if _text_contains_any(text, hard_exclude_keywords):
            continue
        if _is_company_document_like(item, text) and _count_keyword_hits(text, core_variable_keywords) == 0:
            continue
        score = 0
        if _text_contains_any(text, industry_aliases):
            score += 2
        query_hits = _count_keyword_hits(text, query_keywords)
        if query_hits:
            score += min(8, query_hits * 2)
        strong_hits = _count_keyword_hits(text, strong_keywords)
        if strong_hits:
            score += min(6, strong_hits)
        if _count_keyword_hits(text, ["政策", "供给", "需求", "价格", "库存", "资本开支", "开工率", "产量"]) >= 2:
            score += 2
        if _count_keyword_hits(text, core_variable_keywords) >= 2:
            score += 2
        if _text_contains_any(text, sector_report_keywords) and (query_hits >= 1 or strong_hits >= 2):
            score += 1
        if _text_contains_any(text, weak_keywords):
            score -= 3
        if _is_company_document_like(item, text):
            score -= 2
        if score > 1:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [item for _, item in scored[:limit]]
    if ranked:
        return ranked
    return results[:limit]


def _rerank_global_results(
    results: list[dict[str, Any]],
    final_limit: int,
) -> list[dict[str, Any]]:
    trigger_keywords = [
        "霍尔木兹", "原油", "油价", "OPEC", "红海", "航运", "美元指数", "汇率",
        "关税", "地缘", "冲突", "封锁", "天然气", "铜价", "金价", "能源", "中东",
    ]
    transmission_keywords = [
        "供给", "需求", "库存", "运价", "保险", "成本", "供应链", "价格", "断供", "溢价", "风险溢价",
    ]
    weak_keywords = [
        "收评", "午评", "复盘", "ETF", "选哪个", "盘前要闻",
    ]
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in results:
        title = item.get("title", "") or ""
        trunk = item.get("trunk", "") or ""
        text = f"{title} {trunk}"
        score = 0
        trigger_hits = _count_keyword_hits(text, trigger_keywords)
        transmission_hits = _count_keyword_hits(text, transmission_keywords)
        if trigger_hits:
            score += min(5, 2 + trigger_hits)
        if transmission_hits:
            score += min(5, 2 + transmission_hits)
        if trigger_hits and transmission_hits:
            score += 3
        if _text_contains_any(text, weak_keywords):
            score -= 3
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [item for _, item in scored[:final_limit]]
    if ranked:
        return ranked
    return results[:final_limit]


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
    raw["results"] = _rerank_macro_results(deduped_results, industry=industry, queries=queries, limit=limit)
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
            queries=queries,
            limit=final_limit,
        )
    elif rerank_mode == "global":
        raw["results"] = _rerank_global_results(
            deduped_results,
            final_limit=final_limit,
        )
    else:
        raw["results"] = deduped_results[:final_limit]
    raw["reranked_results_count"] = len(raw["results"])
    return raw


def search_mx_custom_event_news(query: str, limit: int = 10) -> dict[str, Any]:
    return mx_search(query, limit=limit)
