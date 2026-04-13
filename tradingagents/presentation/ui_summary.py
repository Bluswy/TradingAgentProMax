from __future__ import annotations

from typing import Any


UI_SUMMARY_SCHEMA_VERSION = "ui_summary.v1"


def _summary_base(
    *,
    agent: str,
    title: str,
    effective_date: str | None,
    summary_zh: str,
    confidence: float | None = None,
    primary_label: str | None = None,
    secondary_label: str | None = None,
    highlights: list[dict[str, Any]] | None = None,
    risks: list[str] | None = None,
    watch_points: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": UI_SUMMARY_SCHEMA_VERSION,
        "agent": agent,
        "title": title,
        "effective_date": effective_date,
        "summary_zh": summary_zh,
        "confidence": confidence,
        "primary_label": primary_label,
        "secondary_label": secondary_label,
        "highlights": highlights or [],
        "risks": risks or [],
        "watch_points": watch_points or [],
        "extra": extra or {},
    }


def build_company_context_ui_summary(company_context: dict[str, Any] | None) -> dict[str, Any]:
    company_context = company_context or {}
    identity = company_context.get("identity", {})
    classification = company_context.get("classification", {})
    business_context = company_context.get("business_context", {})
    return {
        "schema_version": UI_SUMMARY_SCHEMA_VERSION,
        "agent": "company_context",
        "title": "公司上下文",
        "effective_date": company_context.get("analysis_time", {}).get("effective_date"),
        "summary_zh": business_context.get("company_intro", "") or f"{identity.get('company_name') or identity.get('ticker', '')} 上下文已加载。",
        "confidence": None,
        "primary_label": classification.get("industry"),
        "secondary_label": classification.get("company_type"),
        "highlights": [
            {"key": "company_name", "label": "公司", "value": identity.get("company_name"), "tone": "neutral"},
            {"key": "ticker", "label": "代码", "value": identity.get("ticker"), "tone": "neutral"},
            {"key": "industry", "label": "行业", "value": classification.get("industry"), "tone": "neutral"},
            {"key": "company_type", "label": "类型", "value": classification.get("company_type"), "tone": "neutral"},
        ],
        "risks": [],
        "watch_points": business_context.get("demand_drivers", [])[:3],
        "extra": {
            "exchange": identity.get("exchange"),
            "market": identity.get("market"),
            "sub_industry": business_context.get("sub_industry"),
        },
    }


def build_technical_ui_summary(analysis_result: dict[str, Any] | None) -> dict[str, Any]:
    analysis_result = analysis_result or {}
    trend = analysis_result.get("trend", {})
    momentum = analysis_result.get("momentum", {})
    volume = analysis_result.get("volume_confirmation", {})
    relative_strength = analysis_result.get("relative_strength", {})
    return _summary_base(
        agent="technical",
        title="技术分析",
        effective_date=analysis_result.get("effective_trade_date"),
        summary_zh=analysis_result.get("technical_summary_zh", ""),
        confidence=analysis_result.get("confidence"),
        primary_label=trend.get("short_term"),
        secondary_label=momentum.get("state"),
        highlights=[
            {"key": "short_term_trend", "label": "短期趋势", "value": trend.get("short_term"), "tone": "neutral"},
            {"key": "medium_term_trend", "label": "中期趋势", "value": trend.get("medium_term"), "tone": "neutral"},
            {"key": "momentum", "label": "动能", "value": momentum.get("state"), "tone": "neutral"},
            {"key": "volume_confirmation", "label": "量价确认", "value": volume.get("state"), "tone": "neutral"},
            {"key": "relative_strength", "label": "相对强弱", "value": relative_strength.get("vs_benchmark"), "tone": "neutral"},
        ],
        risks=analysis_result.get("risk_flags", [])[:5],
        watch_points=analysis_result.get("invalidations", [])[:5],
        extra={"indicator_snapshot": analysis_result.get("indicator_snapshot", {})},
    )


def build_fundamental_ui_summary(analysis_result: dict[str, Any] | None) -> dict[str, Any]:
    analysis_result = analysis_result or {}
    financial_snapshot = analysis_result.get("financial_snapshot", {}).get("common", {})
    return _summary_base(
        agent="fundamental",
        title="基本面分析",
        effective_date=analysis_result.get("effective_trade_date"),
        summary_zh=analysis_result.get("fundamental_summary_zh", ""),
        confidence=analysis_result.get("confidence"),
        primary_label=analysis_result.get("growth", {}).get("state"),
        secondary_label=analysis_result.get("valuation", {}).get("state"),
        highlights=[
            {"key": "growth", "label": "增长", "value": analysis_result.get("growth", {}).get("state"), "tone": "neutral"},
            {"key": "profitability", "label": "盈利质量", "value": analysis_result.get("profitability", {}).get("state"), "tone": "neutral"},
            {"key": "cashflow", "label": "现金流", "value": analysis_result.get("cashflow_quality", {}).get("state"), "tone": "neutral"},
            {"key": "balance_sheet", "label": "资产负债表", "value": analysis_result.get("balance_sheet_health", {}).get("state"), "tone": "neutral"},
            {"key": "valuation", "label": "估值", "value": analysis_result.get("valuation", {}).get("state"), "tone": "neutral"},
        ],
        risks=analysis_result.get("core_risks", [])[:5],
        watch_points=[signal.get("description", "") for signal in analysis_result.get("fundamental_signals", [])[:4] if signal.get("description")],
        extra={"financial_snapshot": financial_snapshot, "company_type": analysis_result.get("company_profile", {}).get("company_type")},
    )


def build_event_news_ui_summary(analysis_result: dict[str, Any] | None) -> dict[str, Any]:
    analysis_result = analysis_result or {}
    overview = analysis_result.get("event_overview", {})
    snapshot = analysis_result.get("event_context_snapshot", {})
    return _summary_base(
        agent="event_news",
        title="事件与新闻分析",
        effective_date=analysis_result.get("effective_trade_date"),
        summary_zh=analysis_result.get("event_summary_zh", ""),
        confidence=overview.get("confidence"),
        primary_label=overview.get("state"),
        secondary_label=snapshot.get("dominant_driver_layer"),
        highlights=[
            {"key": "event_state", "label": "事件状态", "value": overview.get("state"), "tone": "neutral"},
            {"key": "driver_layer", "label": "主导层", "value": snapshot.get("dominant_driver_layer"), "tone": "neutral"},
            {"key": "chain_completeness", "label": "链路完整度", "value": snapshot.get("chain_completeness"), "tone": "neutral"},
            {"key": "catalyst", "label": "关键催化", "value": snapshot.get("most_actionable_catalyst"), "tone": "positive"},
            {"key": "critical_risk", "label": "关键风险", "value": snapshot.get("most_critical_risk"), "tone": "negative"},
        ],
        risks=analysis_result.get("key_risks", [])[:5],
        watch_points=analysis_result.get("tracking_points", [])[:5],
        extra={
            "company_events": len(analysis_result.get("company_specific_events", [])),
            "industry_events": len(analysis_result.get("industry_macro_events", [])),
            "event_compact_signals": analysis_result.get("event_compact_signals", {}),
        },
    )


def build_sector_flow_ui_summary(analysis_result: dict[str, Any] | None) -> dict[str, Any]:
    analysis_result = analysis_result or {}
    return _summary_base(
        agent="sector_flow",
        title="板块资金面分析",
        effective_date=analysis_result.get("effective_trade_date"),
        summary_zh=analysis_result.get("flow_summary_zh", ""),
        confidence=None,
        primary_label=analysis_result.get("theme_strength", {}).get("state"),
        secondary_label=analysis_result.get("stock_role_in_theme", {}).get("state"),
        highlights=[
            {"key": "theme_strength", "label": "板块强度", "value": analysis_result.get("theme_strength", {}).get("state"), "tone": "neutral"},
            {"key": "theme_heat", "label": "板块热度", "value": analysis_result.get("theme_heat", {}).get("state"), "tone": "neutral"},
            {"key": "crowding", "label": "拥挤度", "value": analysis_result.get("crowding", {}).get("state"), "tone": "neutral"},
            {"key": "stock_role", "label": "个股角色", "value": analysis_result.get("stock_role_in_theme", {}).get("state"), "tone": "neutral"},
            {"key": "flow_persistence", "label": "资金持续性", "value": analysis_result.get("flow_persistence", {}).get("state"), "tone": "neutral"},
        ],
        risks=analysis_result.get("key_risks", [])[:5],
        watch_points=analysis_result.get("tracking_points", [])[:5],
        extra={"compact_signals": analysis_result.get("sector_flow_compact_signals", {})},
    )


def build_strategy_style_ui_summary(analysis_result: dict[str, Any] | None) -> dict[str, Any]:
    analysis_result = analysis_result or {}
    primary = analysis_result.get("primary_strategy", {})
    return _summary_base(
        agent="strategy_style",
        title="策略范式识别",
        effective_date=analysis_result.get("effective_date"),
        summary_zh=analysis_result.get("strategy_summary_zh", ""),
        confidence=primary.get("confidence"),
        primary_label=primary.get("label_zh") or primary.get("type"),
        secondary_label=analysis_result.get("holding_horizon", {}).get("type"),
        highlights=[
            {"key": "primary_strategy", "label": "主策略", "value": primary.get("label_zh") or primary.get("type"), "tone": "neutral"},
            {"key": "holding_horizon", "label": "持有周期", "value": analysis_result.get("holding_horizon", {}).get("type"), "tone": "neutral"},
            {"key": "technical_weight", "label": "技术权重", "value": analysis_result.get("strategy_routing", {}).get("technical_weight"), "tone": "neutral"},
            {"key": "fundamental_weight", "label": "基本面权重", "value": analysis_result.get("strategy_routing", {}).get("fundamental_weight"), "tone": "neutral"},
            {"key": "event_weight", "label": "事件权重", "value": analysis_result.get("strategy_routing", {}).get("event_weight"), "tone": "neutral"},
            {"key": "sector_flow_weight", "label": "资金面权重", "value": analysis_result.get("strategy_routing", {}).get("sector_flow_weight"), "tone": "neutral"},
        ],
        risks=analysis_result.get("strategy_constraints", [])[:5],
        watch_points=analysis_result.get("invalidations", [])[:5],
        extra={
            "secondary_strategies": analysis_result.get("secondary_strategies", []),
            "decision_priority_variables": analysis_result.get("decision_priority_variables", []),
            "decision_kpis": analysis_result.get("decision_kpis", []),
        },
    )


def build_strategy_decision_ui_summary(analysis_result: dict[str, Any] | None) -> dict[str, Any]:
    analysis_result = analysis_result or {}
    decision = analysis_result.get("decision", {})
    execution = analysis_result.get("execution_plan", {})
    watchlist = analysis_result.get("watchlist", [])
    structured_invalidations = analysis_result.get("invalidations_structured", [])
    watch_points = []
    for item in watchlist[:3]:
        if isinstance(item, dict) and item.get("variable"):
            watch_points.append(str(item.get("variable")))
    for item in structured_invalidations[:2]:
        if isinstance(item, dict) and item.get("label"):
            watch_points.append(str(item.get("label")))
    return _summary_base(
        agent="strategy_decision",
        title="策略决策",
        effective_date=analysis_result.get("effective_date"),
        summary_zh=analysis_result.get("decision_summary_zh", ""),
        confidence=decision.get("confidence"),
        primary_label=decision.get("label_zh") or decision.get("action"),
        secondary_label=execution.get("priority"),
        highlights=[
            {"key": "action", "label": "动作", "value": decision.get("label_zh") or decision.get("action"), "tone": "neutral"},
            {"key": "priority", "label": "优先级", "value": execution.get("priority"), "tone": "neutral"},
            {"key": "horizon", "label": "周期", "value": execution.get("horizon"), "tone": "neutral"},
            {"key": "setup", "label": "偏好 setup", "value": execution.get("preferred_setup"), "tone": "neutral"},
            {"key": "positioning_bias", "label": "仓位倾向", "value": execution.get("positioning_bias"), "tone": "neutral"},
        ],
        risks=analysis_result.get("risk_flags", [])[:5],
        watch_points=watch_points or analysis_result.get("trigger_conditions", [])[:5] + analysis_result.get("invalidations", [])[:5],
        extra={
            "core_reasons": analysis_result.get("decision_rationale", {}).get("core_reasons", []),
            "key_conflicts": analysis_result.get("decision_rationale", {}).get("key_conflicts", []),
            "top_supporting_evidence": analysis_result.get("top_supporting_evidence", []),
            "module_contributions": analysis_result.get("module_contributions", {}),
            "primary_risk": analysis_result.get("primary_risk", {}),
            "watchlist": watchlist,
        },
    )


def build_company_report_ui_summary(analysis_result: dict[str, Any] | None) -> dict[str, Any]:
    analysis_result = analysis_result or {}
    return _summary_base(
        agent="company_report",
        title="公司分析报告",
        effective_date=analysis_result.get("effective_date"),
        summary_zh="\n".join(analysis_result.get("executive_summary", [])[:3]),
        confidence=None,
        primary_label=analysis_result.get("report_title"),
        secondary_label=f"{len(analysis_result.get('key_takeaways', []))} key takeaways",
        highlights=[
            {"key": "report_title", "label": "报告标题", "value": analysis_result.get("report_title"), "tone": "neutral"},
            {"key": "executive_summary_count", "label": "执行摘要", "value": len(analysis_result.get("executive_summary", [])), "tone": "neutral"},
            {"key": "key_takeaways_count", "label": "关键结论", "value": len(analysis_result.get("key_takeaways", [])), "tone": "neutral"},
            {"key": "markdown_length", "label": "报告长度", "value": len(analysis_result.get("report_markdown", "")), "tone": "neutral"},
        ],
        risks=[],
        watch_points=analysis_result.get("key_takeaways", [])[:5],
        extra={},
    )


def build_final_report_ui_summary(final_report: dict[str, Any] | None) -> dict[str, Any]:
    final_report = final_report or {}
    decision = final_report.get("decision", {})
    execution = final_report.get("execution_plan", {})
    return _summary_base(
        agent="final_report",
        title="综合报告",
        effective_date=final_report.get("effective_date"),
        summary_zh="\n".join(final_report.get("executive_summary", [])[:4]),
        confidence=decision.get("confidence"),
        primary_label=final_report.get("report_title"),
        secondary_label=decision.get("label_zh") or decision.get("action"),
        highlights=[
            {"key": "report_title", "label": "报告标题", "value": final_report.get("report_title"), "tone": "neutral"},
            {"key": "decision", "label": "当前动作", "value": decision.get("label_zh") or decision.get("action"), "tone": "neutral"},
            {"key": "priority", "label": "优先级", "value": execution.get("priority"), "tone": "neutral"},
            {"key": "horizon", "label": "周期", "value": execution.get("horizon"), "tone": "neutral"},
        ],
        risks=[],
        watch_points=final_report.get("key_takeaways", [])[:5],
        extra={"markdown_length": len(final_report.get("report_markdown", ""))},
    )


def attach_ui_summary(result: dict[str, Any] | None, builder) -> dict[str, Any] | None:
    if result is None:
        return None
    normalized = dict(result)
    analysis_result = normalized.get("analysis_result") or {}
    normalized["ui_summary"] = builder(analysis_result)
    return normalized


def build_ui_summaries(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "company_context": build_company_context_ui_summary(state.get("company_context")),
        "technical": ((state.get("technical_result") or {}).get("ui_summary")) or build_technical_ui_summary(((state.get("technical_result") or {}).get("analysis_result"))),
        "fundamental": ((state.get("fundamental_result") or {}).get("ui_summary")) or build_fundamental_ui_summary(((state.get("fundamental_result") or {}).get("analysis_result"))),
        "event_news": ((state.get("event_news_result") or {}).get("ui_summary")) or build_event_news_ui_summary(((state.get("event_news_result") or {}).get("analysis_result"))),
        "sector_flow": ((state.get("sector_flow_result") or {}).get("ui_summary")) or build_sector_flow_ui_summary(((state.get("sector_flow_result") or {}).get("analysis_result"))),
        "strategy_style": ((state.get("strategy_style_result") or {}).get("ui_summary")) or build_strategy_style_ui_summary(((state.get("strategy_style_result") or {}).get("analysis_result"))),
        "strategy_decision": ((state.get("strategy_decision_result") or {}).get("ui_summary")) or build_strategy_decision_ui_summary(((state.get("strategy_decision_result") or {}).get("analysis_result"))),
        "company_report": ((state.get("company_report_result") or {}).get("ui_summary")) or build_company_report_ui_summary(((state.get("company_report_result") or {}).get("analysis_result"))),
        "final_report": build_final_report_ui_summary(state.get("final_report_result")),
    }
