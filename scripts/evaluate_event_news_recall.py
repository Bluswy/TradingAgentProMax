#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from datetime import datetime
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.event_news_bundle_service import build_event_news_data_bundle
from tradingagents.default_config import DEFAULT_CONFIG


NOISE_KEYWORDS = [
    "盘前要闻",
    "收评",
    "午评",
    "复盘",
    "etf",
    "选哪个",
    "基金重仓",
    "浮亏",
    "快讯汇总",
    "异动点评",
    "涨停复盘",
    "募集说明书",
    "债券",
    "融资券",
    "超短期融资券",
    "公司债",
    "中期票据",
    "上会稿",
    "招股说明书",
]

COMPANY_EVENT_DIMENSIONS = {
    "earnings": ["业绩", "预告", "快报", "年报", "季报", "一季报", "半年报", "净利", "营收", "利润"],
    "orders_projects": ["订单", "合同", "中标", "项目", "复产", "投产", "扩产", "产能", "项目进展"],
    "capital_markets": ["回购", "增持", "减持", "定增", "发债", "融资", "贷款", "担保", "股权", "并购", "重组"],
    "regulatory_risk": ["监管", "问询", "处罚", "诉讼", "违约", "风险", "工作函", "立案", "调查"],
    "operations": ["停产", "复工", "交付", "客户", "新品", "认证", "量产", "签约"],
}

INDUSTRY_EVENT_DIMENSIONS = {
    "policy": ["政策", "规划", "补贴", "监管", "关税", "牌照", "招标规则", "集采"],
    "supply": ["供给", "产量", "产能", "开工率", "停产", "检修", "扩产", "限产"],
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

TRANSMISSION_DIMENSIONS = {
    "supply_demand": ["供给", "需求", "产量", "库存", "进口", "出口", "补库", "去库"],
    "cost_margin": ["成本", "毛利", "利润", "价差", "战争险", "保险"],
    "pricing": ["价格", "油价", "运价", "汇率", "利率"],
    "investment": ["资本开支", "capex", "勘探开发", "扩产", "开工率"],
    "risk_appetite": ["风险偏好", "避险", "估值", "风险溢价"],
}

LLM_JUDGE_SYSTEM_PROMPT = """
你是一个 EventNewsAgent 质量评估器。你的任务是判断：
1. 召回结果是否足够支撑后续股票分析 Agent 进行事件传导分析；
2. EventNewsAgent 最终返回结果是否形成了可供上层 Agent 直接消费的结构化上下文。

请重点评估以下标准：
1. 公司层是否覆盖硬事件：业绩、订单/项目、资本运作、监管/诉讼、重大经营变化。
2. 行业层是否覆盖关键变量：政策、供给、需求、价格/景气、资本开支/库存、技术/竞争格局。
3. 全球层是否覆盖“触发因素 + 传导变量”：例如地缘/OPEC/汇率/利率 与 供给、价格、运价、保险、库存、成本的联动。
4. 三层是否能拼成一条从全球/行业到公司的事件传导链，而不是各说各话。
5. 最终输出是否具备高相关性、强逻辑链、低幻觉，并且对上层 Agent 有决策价值。
6. 最终输出是否包含结构化上下文：事件概览、事件对象、事件链、关键催化、关键风险、跟踪点、上下文快照。
7. 噪声是否足够低，结果是否偏向可执行事件而不是盘面评论、ETF导流或无新增信息摘要。

输出要求：
- 只输出 JSON
- 不要输出 Markdown
- 按指定字段返回四维评分、召回质量、最终输出质量、传导链充分性和改进建议
""".strip()

LLM_JSON_REPAIR_SYSTEM_PROMPT = """
你是一个 JSON 修复器。你的任务是把输入内容修复为合法 JSON。

要求：
- 只输出合法 JSON
- 不要输出解释
- 不要补充输入中不存在的新结论，只做最小必要修复
""".strip()


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def _matched_dimensions(text: str, dimension_map: dict[str, list[str]]) -> dict[str, list[str]]:
    matched: dict[str, list[str]] = {}
    for dim, keywords in dimension_map.items():
        hits = _matched_keywords(text, keywords)
        if hits:
            matched[dim] = hits
    return matched


def _build_item_eval(layer: str, item: dict[str, Any], company_name: str, ticker: str, industry: str) -> dict[str, Any]:
    title = str(item.get("title", "") or "")
    trunk = str(item.get("trunk", "") or "")
    text = f"{title} {trunk}"
    score = 0
    reasons: list[str] = []

    if layer == "company":
        aliases = [company_name, ticker, ticker.split(".")[0]]
        alias_hits = _matched_keywords(text, [alias for alias in aliases if alias])
        event_dims = _matched_dimensions(text, COMPANY_EVENT_DIMENSIONS)
        if alias_hits:
            score += 4
            reasons.append(f"命中公司标识: {alias_hits}")
        if event_dims:
            score += min(5, len(event_dims) + 1)
            reasons.append(f"命中公司事件维度: {sorted(event_dims)}")
        actionable = bool(event_dims)
        dimensions = event_dims
    elif layer == "industry":
        industry_hits = _matched_keywords(text, [industry] if industry else [])
        event_dims = _matched_dimensions(text, INDUSTRY_EVENT_DIMENSIONS)
        if industry_hits:
            score += 3
            reasons.append(f"命中行业词: {industry_hits}")
        if event_dims:
            score += min(5, len(event_dims))
            reasons.append(f"命中行业变量维度: {sorted(event_dims)}")
        actionable = bool(event_dims)
        dimensions = event_dims
    else:
        trigger_dims = _matched_dimensions(text, GLOBAL_TRIGGER_DIMENSIONS)
        transmission_dims = _matched_dimensions(text, TRANSMISSION_DIMENSIONS)
        if trigger_dims:
            score += 4
            reasons.append(f"命中全球触发维度: {sorted(trigger_dims)}")
        if transmission_dims:
            score += 4
            reasons.append(f"命中传导变量维度: {sorted(transmission_dims)}")
        if trigger_dims and transmission_dims:
            score += 3
            reasons.append("同时覆盖全球触发与传导变量")
        actionable = bool(trigger_dims) and bool(transmission_dims)
        dimensions = {"trigger": sorted(trigger_dims), "transmission": sorted(transmission_dims)}

    noise_hits = _matched_keywords(text, NOISE_KEYWORDS)
    if noise_hits:
        score -= 4
        reasons.append(f"命中噪声词: {noise_hits}")

    return {
        "title": title,
        "score": score,
        "reasons": reasons,
        "dimensions": dimensions,
        "is_noise": bool(noise_hits),
        "is_actionable": actionable,
    }


def _grade_layer(layer: str, result_count: int, actionable_count: int, avg_score: float, diversity: int, noise_count: int) -> str:
    if result_count == 0:
        return "poor"
    noise_ratio = noise_count / max(result_count, 1)
    actionable_ratio = actionable_count / max(result_count, 1)

    if layer == "company":
        if actionable_count >= 3 and diversity >= 2 and actionable_ratio >= 0.6 and avg_score >= 5 and noise_ratio <= 0.2:
            return "strong"
        if actionable_count >= 2 and diversity >= 1 and avg_score >= 2:
            return "usable"
        return "poor"

    if layer == "industry":
        if actionable_count >= 3 and diversity >= 3 and actionable_ratio >= 0.6 and avg_score >= 3 and noise_ratio <= 0.2:
            return "strong"
        if actionable_count >= 2 and diversity >= 2 and avg_score >= 1.5:
            return "usable"
        return "poor"

    if actionable_count >= 2 and diversity >= 2 and actionable_ratio >= 0.5 and avg_score >= 4 and noise_ratio <= 0.2:
        return "strong"
    if actionable_count >= 1 and diversity >= 1 and avg_score >= 2:
        return "usable"
    return "poor"


def _flatten_layer_dimensions(layer: str, items: list[dict[str, Any]]) -> set[str]:
    flattened: set[str] = set()
    for item in items:
        dims = item.get("dimensions", {})
        if layer == "global":
            flattened.update(dims.get("trigger", []))
            flattened.update(dims.get("transmission", []))
        else:
            flattened.update(dims.keys())
    return flattened


def _evaluate_layer(layer: str, trace: dict[str, Any], company_name: str, ticker: str, industry: str) -> dict[str, Any]:
    results = trace.get("results", []) or []
    items = [_build_item_eval(layer, item, company_name, ticker, industry) for item in results]
    actionable_count = sum(1 for item in items if item["is_actionable"])
    noise_count = sum(1 for item in items if item["is_noise"])
    avg_score = round(sum(item["score"] for item in items) / len(items), 2) if items else 0.0
    dimension_coverage = sorted(_flatten_layer_dimensions(layer, items))
    quality_grade = _grade_layer(layer, len(items), actionable_count, avg_score, len(dimension_coverage), noise_count)

    if layer == "company":
        coverage_hint = "公司层应覆盖业绩、订单/项目、资本运作、监管/诉讼等硬事件，至少命中两个维度。"
    elif layer == "industry":
        coverage_hint = "行业层应覆盖政策、供给、需求、价格/景气、资本开支/库存、技术/竞争格局中的多个维度。"
    else:
        coverage_hint = "全球层应同时命中全球触发因素与传导变量，不能只有泛宏观叙事。"

    return {
        "queries": trace.get("queries", []),
        "result_count": len(results),
        "deduped_results_count": trace.get("deduped_results_count"),
        "reranked_results_count": trace.get("reranked_results_count"),
        "avg_item_score": avg_score,
        "actionable_count": actionable_count,
        "noise_count": noise_count,
        "dimension_coverage": dimension_coverage,
        "quality_grade": quality_grade,
        "coverage_hint": coverage_hint,
        "items": items,
    }


def _evaluate_chain_closure(company_eval: dict[str, Any], industry_eval: dict[str, Any], global_eval: dict[str, Any]) -> dict[str, Any]:
    company_dims = set(company_eval["dimension_coverage"])
    industry_dims = set(industry_eval["dimension_coverage"])
    global_dims = set(global_eval["dimension_coverage"])

    industry_has_variables = bool(industry_dims & {"policy", "supply", "demand", "price_cycle", "capex_inventory", "technology_competition"})
    global_has_trigger = bool(global_dims & {"geopolitics", "commodity", "macro_policy", "logistics"})
    global_has_transmission = bool(global_dims & {"supply_demand", "cost_margin", "pricing", "investment", "risk_appetite"})
    company_has_impact = bool(company_dims & {"earnings", "orders_projects", "capital_markets", "regulatory_risk", "operations"})

    satisfied = {
        "company_impact": company_has_impact,
        "industry_variables": industry_has_variables,
        "global_trigger": global_has_trigger,
        "global_transmission": global_has_transmission,
    }
    satisfied_count = sum(1 for value in satisfied.values() if value)

    grade = "poor"
    if satisfied_count == 4:
        grade = "strong"
    elif satisfied_count >= 3:
        grade = "usable"

    return {
        "satisfied": satisfied,
        "satisfied_count": satisfied_count,
        "quality_grade": grade,
        "summary": (
            "事件传导链应至少覆盖：全球触发、全球传导变量、行业变量、公司影响。"
            f" 当前满足 {satisfied_count}/4。"
        ),
    }


def _build_rule_based_report(bundle: dict[str, Any]) -> dict[str, Any]:
    trace = bundle.get("debug_trace", {})
    meta = bundle.get("meta", {})
    company_name = str(meta.get("name") or bundle.get("ticker") or "")
    ticker = str(bundle.get("ticker") or "")
    industry = str(meta.get("industry") or "")

    company_eval = _evaluate_layer("company", trace.get("company_search", {}), company_name, ticker, industry)
    industry_eval = _evaluate_layer("industry", trace.get("industry_search", {}), company_name, ticker, industry)
    global_eval = _evaluate_layer("global", trace.get("global_search", {}), company_name, ticker, industry)
    chain_closure = _evaluate_chain_closure(company_eval, industry_eval, global_eval)

    non_empty_layers = sum(1 for layer in (company_eval, industry_eval, global_eval) if layer["result_count"] > 0)
    actionable_layers = sum(1 for layer in (company_eval, industry_eval, global_eval) if layer["actionable_count"] > 0)
    strong_layers = sum(1 for layer in (company_eval, industry_eval, global_eval) if layer["quality_grade"] == "strong")

    overall_grade = "poor"
    if non_empty_layers == 3 and actionable_layers == 3 and strong_layers >= 2 and chain_closure["quality_grade"] == "strong":
        overall_grade = "production_ready"
    elif non_empty_layers == 3 and actionable_layers >= 2 and chain_closure["quality_grade"] in {"usable", "strong"}:
        overall_grade = "strong"
    elif non_empty_layers >= 2 and actionable_layers >= 2:
        overall_grade = "usable"

    evaluation_standard = {
        "高标准定义": "高质量召回不是新闻越多越好，而是用尽可能少的结果覆盖足够完整的事件上下文和传导路径。",
        "公司层": "高质量结果应优先是公司硬事件，例如业绩、订单/项目、资本运作、监管/诉讼、重大经营变化。",
        "行业层": "高质量结果应覆盖会改变板块基本面的变量，例如政策、供给、需求、价格/景气、资本开支/库存、技术/竞争格局。",
        "全球层": "高质量结果应同时覆盖全球触发因素和传导变量，例如地缘/OPEC/汇率/利率 与 供给、价格、运价、保险、库存、成本。",
        "传导链": "三层结果需要能拼成从全球/行业到公司的事件传导链，而不是各层各说各话。",
        "输出目标": "召回结果应足以让上层 Agent 回答：发生了什么、改变了哪些变量、影响哪一层、接下来该跟踪什么。",
    }

    debug_trace = bundle.get("debug_trace", {})
    retrieval_runtime_snapshot = {
        "company": {
            "queries": debug_trace.get("company_search", {}).get("queries", []),
            "deduped_results_count": debug_trace.get("company_search", {}).get("deduped_results_count"),
            "reranked_results_count": debug_trace.get("company_search", {}).get("reranked_results_count"),
        },
        "industry": {
            "queries": debug_trace.get("industry_search", {}).get("queries", []),
            "deduped_results_count": debug_trace.get("industry_search", {}).get("deduped_results_count"),
            "reranked_results_count": debug_trace.get("industry_search", {}).get("reranked_results_count"),
        },
        "global": {
            "queries": debug_trace.get("global_search", {}).get("queries", []),
            "deduped_results_count": debug_trace.get("global_search", {}).get("deduped_results_count"),
            "reranked_results_count": debug_trace.get("global_search", {}).get("reranked_results_count"),
        },
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_type": "event_news_recall_evaluation",
        "report_scope": "fresh_runtime_bundle",
        "design_basis": "latest_event_news_agent_company_context_design",
        "ticker": ticker,
        "analysis_date": bundle.get("requested_date"),
        "company_name": company_name,
        "industry": industry,
        "query_plan": trace.get("query_plan", {}),
        "retrieval_runtime_snapshot": retrieval_runtime_snapshot,
        "evaluation_standard": evaluation_standard,
        "rule_based_evaluation": {
            "layer_evaluation": {
                "company": company_eval,
                "industry": industry_eval,
                "global": global_eval,
            },
            "chain_closure": chain_closure,
            "overall": {
                "non_empty_layers": non_empty_layers,
                "actionable_layers": actionable_layers,
                "strong_layers": strong_layers,
                "quality_grade": overall_grade,
                "summary": (
                    f"三层中有 {non_empty_layers}/3 层有结果，"
                    f"{actionable_layers}/3 层包含可执行事件线索，"
                    f"{strong_layers}/3 层达到 strong，"
                    f"传导链评估为 {chain_closure['quality_grade']}。"
                ),
            },
        },
    }


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").lower())


def _titles_from_results(results: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("title", "") or "") for item in results if str(item.get("title", "") or "").strip()]


def _collect_grounding_titles(bundle: dict[str, Any]) -> set[str]:
    trace = bundle.get("debug_trace", {})
    titles: set[str] = set()
    for layer in ("company_search", "industry_search", "global_search"):
        titles.update(_titles_from_results(_safe_list(_safe_dict(trace.get(layer)).get("results"))))
    for key in ("normalized_company_events", "normalized_industry_events", "normalized_global_events"):
        for item in _safe_list(trace.get(key)):
            title = str(_safe_dict(item).get("title", "") or "")
            if title:
                titles.add(title)
            titles.update(str(x) for x in _safe_list(_safe_dict(item).get("evidence_titles")) if str(x).strip())
    return {title for title in titles if title.strip()}


def _is_grounded_text(text: str, grounding_titles: set[str]) -> bool:
    normalized = _compact_text(text)
    if not normalized:
        return False
    for title in grounding_titles:
        title_norm = _compact_text(title)
        if not title_norm:
            continue
        if title_norm in normalized or normalized in title_norm:
            return True
    return False


def _evaluate_output_events(events: list[dict[str, Any]], grounding_titles: set[str]) -> dict[str, Any]:
    field_scores: list[int] = []
    evidence_grounded = 0
    summaries = 0
    variables = 0
    valid_titles = 0
    time_horizons = 0
    directions = 0
    event_types = 0

    for event in events:
        event = _safe_dict(event)
        score = 0
        if str(event.get("title", "") or "").strip():
            valid_titles += 1
            score += 1
        if str(event.get("summary", "") or "").strip():
            summaries += 1
            score += 1
        if _safe_list(event.get("affected_variables")):
            variables += 1
            score += 1
        if _safe_list(event.get("evidence")):
            score += 1
            if any(_is_grounded_text(str(ev), grounding_titles) for ev in _safe_list(event.get("evidence"))):
                evidence_grounded += 1
        if str(event.get("time_horizon", "") or "").strip():
            time_horizons += 1
            score += 1
        if str(event.get("direction", "") or "").strip():
            directions += 1
        if str(event.get("event_type", "") or "").strip():
            event_types += 1
        field_scores.append(score)

    count = len(events)
    avg_field_score = round(sum(field_scores) / count, 2) if count else 0.0
    grounded_ratio = round(evidence_grounded / count, 2) if count else 0.0
    return {
        "count": count,
        "avg_field_score": avg_field_score,
        "grounded_ratio": grounded_ratio,
        "summary_coverage": round(summaries / count, 2) if count else 0.0,
        "variables_coverage": round(variables / count, 2) if count else 0.0,
        "title_coverage": round(valid_titles / count, 2) if count else 0.0,
        "time_horizon_coverage": round(time_horizons / count, 2) if count else 0.0,
        "direction_coverage": round(directions / count, 2) if count else 0.0,
        "event_type_coverage": round(event_types / count, 2) if count else 0.0,
    }


def _score_bucket(value: float, strong_cutoff: float, usable_cutoff: float) -> str:
    if value >= strong_cutoff:
        return "strong"
    if value >= usable_cutoff:
        return "usable"
    return "poor"


def _evaluate_final_output(bundle: dict[str, Any], retrieval_grade: str, analysis_result: dict[str, Any] | None) -> dict[str, Any]:
    result = _safe_dict(analysis_result)
    grounding_titles = _collect_grounding_titles(bundle)

    overview = _safe_dict(result.get("event_overview"))
    snapshot = _safe_dict(result.get("event_context_snapshot"))
    chain = _safe_dict(result.get("event_chain"))
    company_events = [_safe_dict(item) for item in _safe_list(result.get("company_specific_events"))]
    industry_events = [_safe_dict(item) for item in _safe_list(result.get("industry_macro_events"))]
    catalysts = [str(item).strip() for item in _safe_list(result.get("key_catalysts")) if str(item).strip()]
    risks = [str(item).strip() for item in _safe_list(result.get("key_risks")) if str(item).strip()]
    tracking_points = [str(item).strip() for item in _safe_list(result.get("tracking_points")) if str(item).strip()]

    overview_ok = bool(str(overview.get("summary", "") or "").strip())
    snapshot_fields = [
        "company_event_strength",
        "industry_context_strength",
        "global_context_strength",
        "chain_completeness",
        "dominant_driver_layer",
        "dominant_driver_type",
        "primary_bullish_variable",
        "primary_bearish_variable",
        "most_actionable_catalyst",
        "most_critical_risk",
    ]
    snapshot_filled = [field for field in snapshot_fields if str(snapshot.get(field, "") or "").strip()]
    snapshot_fill_ratio = round(len(snapshot_filled) / len(snapshot_fields), 2)

    chain_counts = {
        "global_triggers": len(_safe_list(chain.get("global_triggers"))),
        "industry_variables": len(_safe_list(chain.get("industry_variables"))),
        "company_impacts": len(_safe_list(chain.get("company_impacts"))),
        "missing_links": len(_safe_list(chain.get("missing_links"))),
    }
    chain_layer_coverage = sum(
        1
        for name in ("global_triggers", "industry_variables", "company_impacts")
        if chain_counts[name] > 0
    )
    chain_grade = "poor"
    if chain_layer_coverage == 3:
        chain_grade = "strong"
    elif chain_layer_coverage >= 2:
        chain_grade = "usable"

    company_eval = _evaluate_output_events(company_events, grounding_titles)
    industry_eval = _evaluate_output_events(industry_events, grounding_titles)
    all_events = company_events + industry_events
    all_event_eval = _evaluate_output_events(all_events, grounding_titles)

    recall_score = 5.0
    if retrieval_grade == "poor":
        recall_score = 2.0
    elif retrieval_grade == "usable":
        recall_score = 3.5
    elif retrieval_grade == "strong":
        recall_score = 4.2
    if all_event_eval["count"] < 2:
        recall_score -= 1.0
    if chain_layer_coverage < 3:
        recall_score -= 0.5
    recall_score = round(max(0.0, min(5.0, recall_score)), 2)

    relevance_score = round(
        min(
            5.0,
            1.5
            + all_event_eval["grounded_ratio"] * 2.0
            + all_event_eval["summary_coverage"] * 0.8
            + all_event_eval["variables_coverage"] * 0.7,
        ),
        2,
    )
    reasoning_chain_score = round(
        min(
            5.0,
            1.0
            + chain_layer_coverage * 1.0
            + snapshot_fill_ratio * 1.0
            + (0.5 if chain_counts["missing_links"] > 0 else 0.0),
        ),
        2,
    )
    structured_context_score = round(
        min(
            5.0,
            1.0
            + snapshot_fill_ratio * 1.5
            + min(len(catalysts), 3) * 0.4
            + min(len(risks), 3) * 0.4
            + min(len(tracking_points), 4) * 0.25
            + (0.5 if overview_ok else 0.0),
        ),
        2,
    )
    overall_score = round(
        (recall_score * 0.3 + relevance_score * 0.25 + reasoning_chain_score * 0.25 + structured_context_score * 0.2),
        2,
    )

    missing_context: list[str] = []
    if not overview_ok:
        missing_context.append("缺 event_overview.summary")
    if company_eval["count"] == 0:
        missing_context.append("缺 company_specific_events")
    if industry_eval["count"] == 0:
        missing_context.append("缺 industry_macro_events")
    if chain_layer_coverage < 3:
        missing_context.append("event_chain 未完整覆盖 global/industry/company 三层")
    if snapshot_fill_ratio < 1.0:
        missing_context.append("event_context_snapshot 存在空字段")
    if len(catalysts) < 2:
        missing_context.append("key_catalysts 偏少")
    if len(risks) < 2:
        missing_context.append("key_risks 偏少")
    if len(tracking_points) < 2:
        missing_context.append("tracking_points 偏少")
    if all_event_eval["grounded_ratio"] < 0.6:
        missing_context.append("事件 evidence 与召回结果的 grounding 偏弱")

    return {
        "evaluation_standard": {
            "Recall": "是否召回并保留了足够多的公司/行业/全球有效事件，支撑事件驱动分析，而不是只抓到零散标题。",
            "Relevance": "最终输出中的事件、证据和变量是否真正来自召回结果，且与公司主线相关。",
            "Reasoning_Chain": "是否形成 global -> industry -> company 的传导链，并显式暴露缺失链路。",
            "Structured_Context": "是否能直接给上层 Agent 提供 overview / event objects / chain / catalysts / risks / tracking points / snapshot。",
        },
        "overview_quality": {
            "has_summary": overview_ok,
            "state": overview.get("state"),
            "confidence": overview.get("confidence"),
        },
        "event_objects": {
            "company": company_eval,
            "industry_macro": industry_eval,
            "all_events": all_event_eval,
        },
        "event_chain_quality": {
            "counts": chain_counts,
            "layer_coverage": chain_layer_coverage,
            "quality_grade": chain_grade,
        },
        "context_pack_quality": {
            "snapshot_fill_ratio": snapshot_fill_ratio,
            "filled_snapshot_fields": snapshot_filled,
            "key_catalysts_count": len(catalysts),
            "key_risks_count": len(risks),
            "tracking_points_count": len(tracking_points),
            "event_summary_present": bool(str(result.get("event_summary_zh", "") or "").strip()),
        },
        "dimension_scores": {
            "recall": recall_score,
            "relevance": relevance_score,
            "reasoning_chain": reasoning_chain_score,
            "structured_context": structured_context_score,
            "overall": overall_score,
        },
        "dimension_grades": {
            "recall": _score_bucket(recall_score, 4.2, 3.0),
            "relevance": _score_bucket(relevance_score, 4.0, 3.0),
            "reasoning_chain": _score_bucket(reasoning_chain_score, 4.0, 3.0),
            "structured_context": _score_bucket(structured_context_score, 4.0, 3.0),
            "overall": _score_bucket(overall_score, 4.0, 3.0),
        },
        "missing_context": missing_context,
        "success_definition": {
            "production_ready": "四个维度都 >= 4.0，且不存在缺失 company/industry 事件或断裂的 event_chain。",
            "usable": "overall >= 3.0，且至少能形成两层以上事件链并给出 catalysts/risks/tracking_points。",
        },
    }


def _load_bundle_from_debug_result(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if "event_news_data_bundle" in payload:
        return _safe_dict(payload.get("event_news_data_bundle")), _safe_dict(payload.get("analysis_result"))

    bundle = {
        "ticker": payload.get("ticker") or _safe_dict(payload.get("company_context", {})).get("identity", {}).get("ticker"),
        "requested_date": payload.get("requested_date") or _safe_dict(payload.get("company_context", {})).get("analysis_time", {}).get("requested_date"),
        "effective_trade_date": payload.get("effective_trade_date") or _safe_dict(payload.get("analysis_result", {})).get("effective_trade_date"),
        "meta": {
            "name": _safe_dict(payload.get("company_context", {})).get("identity", {}).get("company_name"),
            "industry": _safe_dict(payload.get("company_context", {})).get("classification", {}).get("industry"),
            "market": _safe_dict(payload.get("company_context", {})).get("identity", {}).get("market"),
        },
        "query_plan": payload.get("query_plan", {}),
        "event_chain": _safe_dict(payload.get("analysis_result", {})).get("event_chain") or payload.get("event_chain", {}),
        "event_context_snapshot": _safe_dict(payload.get("analysis_result", {})).get("event_context_snapshot") or payload.get("event_context_snapshot", {}),
        "event_compact_signals": _safe_dict(payload.get("analysis_result", {})).get("event_compact_signals") or payload.get("event_compact_signals", {}),
        "debug_trace": {
            "query_plan": payload.get("query_plan", {}),
            "company_search": payload.get("company_search", {}),
            "industry_search": payload.get("industry_search", {}),
            "global_search": payload.get("global_search", {}),
            "normalized_company_events": payload.get("normalized_company_events", []),
            "normalized_industry_events": payload.get("normalized_industry_events", []),
            "normalized_global_events": payload.get("normalized_global_events", []),
            "event_chain": _safe_dict(payload.get("analysis_result", {})).get("event_chain") or payload.get("event_chain", {}),
            "event_context_snapshot": _safe_dict(payload.get("analysis_result", {})).get("event_context_snapshot") or payload.get("event_context_snapshot", {}),
        },
    }
    return bundle, _safe_dict(payload.get("analysis_result"))


def _build_llm_judge_payload(bundle: dict[str, Any], report: dict[str, Any], analysis_result: dict[str, Any] | None) -> dict[str, Any]:
    trace = bundle.get("debug_trace", {})

    def compact_layer(name: str) -> dict[str, Any]:
        layer = report["rule_based_evaluation"]["layer_evaluation"][name]
        raw = trace.get(f"{name}_search", {}) if name in {"company", "industry", "global"} else {}
        return {
            "queries": layer.get("queries", []),
            "quality_grade": layer.get("quality_grade"),
            "dimension_coverage": layer.get("dimension_coverage", []),
            "top_titles": [item.get("title", "") for item in raw.get("results", [])[:8]],
        }

    result = _safe_dict(analysis_result)
    final_output_eval = report.get("final_output_evaluation", {})
    return {
        "ticker": report["ticker"],
        "company_name": report["company_name"],
        "industry": report["industry"],
        "analysis_date": report["analysis_date"],
        "query_plan": report["query_plan"],
        "rule_based_overall": report["rule_based_evaluation"]["overall"],
        "company_layer": compact_layer("company"),
        "industry_layer": compact_layer("industry"),
        "global_layer": compact_layer("global"),
        "chain_closure": report["rule_based_evaluation"]["chain_closure"],
        "final_output_evaluation": final_output_eval,
        "final_output_compact": {
            "event_overview": result.get("event_overview", {}),
            "company_event_titles": [item.get("title", "") for item in _safe_list(result.get("company_specific_events"))[:5]],
            "industry_event_titles": [item.get("title", "") for item in _safe_list(result.get("industry_macro_events"))[:5]],
            "event_chain": result.get("event_chain", {}),
            "key_catalysts": _safe_list(result.get("key_catalysts"))[:5],
            "key_risks": _safe_list(result.get("key_risks"))[:5],
            "tracking_points": _safe_list(result.get("tracking_points"))[:5],
            "event_summary_zh": result.get("event_summary_zh", ""),
        },
    }


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return text


def _extract_balanced_json(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _apply_common_json_repairs(text: str) -> str:
    repaired = text
    repaired = repaired.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = re.sub(r"^\s*json\s*", "", repaired, flags=re.IGNORECASE)
    return repaired.strip()


def _parse_json_with_fallback(text: str) -> dict[str, Any]:
    cleaned = _strip_code_fences(text)
    candidates = [cleaned]
    balanced = _extract_balanced_json(cleaned)
    if balanced and balanced not in candidates:
        candidates.append(balanced)

    for candidate in candidates:
        for variant in (candidate, _apply_common_json_repairs(candidate)):
            try:
                return json.loads(variant)
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("Unable to parse JSON", cleaned, 0)


def _repair_json_with_llm(llm: Any, text: str) -> dict[str, Any]:
    repair_prompt = (
        "请把下面内容修复成合法 JSON，只输出 JSON：\n\n"
        f"{text}"
    )
    response = llm.invoke(
        [
            {"role": "system", "content": LLM_JSON_REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": repair_prompt},
        ]
    )
    return _parse_json_with_fallback(str(response.content))


def _call_llm_judge(payload: dict[str, Any]) -> dict[str, Any]:
    from tradingagents.llm_clients import create_llm_client

    config = DEFAULT_CONFIG.copy()
    set_config(config)

    llm_kwargs: dict[str, Any] = {"project_dir": config.get("project_dir")}
    if config.get("llm_provider") == "openai" and config.get("openai_reasoning_effort"):
        llm_kwargs["reasoning_effort"] = config.get("openai_reasoning_effort")
    if config.get("llm_provider") == "google" and config.get("google_thinking_level"):
        llm_kwargs["thinking_level"] = config.get("google_thinking_level")
    if config.get("llm_provider") in ("bailian", "dashscope"):
        if config.get("bailian_api_key"):
            llm_kwargs["api_key"] = config.get("bailian_api_key")
        llm_kwargs["bailian_enable_thinking"] = config.get("bailian_enable_thinking")
        if config.get("bailian_thinking_budget") is not None:
            llm_kwargs["bailian_thinking_budget"] = config.get("bailian_thinking_budget")

    llm_client = create_llm_client(
        provider=config["llm_provider"],
        model=config.get("deep_think_llm", "qwen3.5-plus"),
        base_url=config.get("backend_url"),
        **llm_kwargs,
    )
    llm = llm_client.get_llm()
    user_prompt = (
        "请基于以下 EventNewsAgent 质量信息，判断这些结果是否足以支撑后续事件驱动股票分析 Agent。"
        "请特别评估 Recall、Relevance、Reasoning Chain、Structured Context 四个维度，"
        "同时区分 retrieval 质量和 final output 质量。\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "只输出 JSON，包含字段："
        "dimension_scores(recall, relevance, reasoning_chain, structured_context, overall, 每项 0-5), "
        "layer_judgement(company, industry, global 各含 quality_grade, sufficiency, missing_context), "
        "retrieval_judgement(quality_grade, summary), "
        "output_judgement(quality_grade, summary, missing_context), "
        "chain_closure(quality_grade, summary), "
        "overall(quality_grade, summary), "
        "recommendations(数组)。"
    )
    response = llm.invoke(
        [
            {"role": "system", "content": LLM_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )
    try:
        return _parse_json_with_fallback(str(response.content))
    except json.JSONDecodeError:
        return _repair_json_with_llm(llm, str(response.content))


def _merge_llm_evaluation(report: dict[str, Any], llm_eval: dict[str, Any]) -> dict[str, Any]:
    report["llm_evaluation"] = llm_eval
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="评估 EventNewsAgent 新闻召回质量。")
    parser.add_argument("--ticker", help="股票代码，例如 600759.SH")
    parser.add_argument("--date", help="分析日期，例如 2026-03-29")
    parser.add_argument(
        "--result-json",
        help="可选，传入已保存的 event_news_agent 调试结果 JSON，直接回放评测 retrieval + final output。",
    )
    parser.add_argument("--use-llm", action="store_true", help="可选，调用 LLM 对召回充分性做复核评估。")
    parser.add_argument(
        "--output",
        help="可选，输出 JSON 文件路径。如果不传则打印到标准输出。",
    )
    args = parser.parse_args()

    if args.result_json:
        bundle, analysis_result = _load_bundle_from_debug_result(Path(args.result_json))
    else:
        if not args.ticker or not args.date:
            parser.error("不使用 --result-json 时，必须提供 --ticker 和 --date。")
        bundle = build_event_news_data_bundle(args.ticker, args.date)
        analysis_result = None

    report = _build_rule_based_report(bundle)
    report["final_output_evaluation"] = _evaluate_final_output(
        bundle,
        report["rule_based_evaluation"]["overall"]["quality_grade"],
        analysis_result,
    )

    if args.use_llm:
        llm_payload = _build_llm_judge_payload(bundle, report, analysis_result)
        try:
            report = _merge_llm_evaluation(report, _call_llm_judge(llm_payload))
        except Exception as exc:
            report["llm_evaluation_error"] = str(exc)

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
        print(f"saved_report={output_path}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
