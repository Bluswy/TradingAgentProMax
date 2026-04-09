from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.llm_clients import create_llm_client
from tradingagents.dataflows.tushare_provider import _normalize_symbol, _read_or_query, _require_tushare


DEFAULT_TIMEZONE = "Asia/Shanghai"


def _default_analysis_date() -> str:
    return datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y-%m-%d")


def _strip_json_block(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _call_parse_llm(config: dict[str, Any], query_text: str) -> dict[str, Any]:
    llm_kwargs: dict[str, Any] = {"project_dir": config.get("project_dir")}
    provider = config.get("llm_provider")
    if provider == "openai" and config.get("openai_reasoning_effort"):
        llm_kwargs["reasoning_effort"] = config.get("openai_reasoning_effort")
    if provider == "google" and config.get("google_thinking_level"):
        llm_kwargs["thinking_level"] = config.get("google_thinking_level")
    if provider in ("bailian", "dashscope") and config.get("bailian_api_key"):
        llm_kwargs["api_key"] = config.get("bailian_api_key")
        llm_kwargs["bailian_enable_thinking"] = config.get("bailian_enable_thinking")
        if config.get("bailian_thinking_budget") is not None:
            llm_kwargs["bailian_thinking_budget"] = config.get("bailian_thinking_budget")

    llm = create_llm_client(
        provider=provider,
        model=config.get("quick_think_llm", "qwen3.5-flash"),
        base_url=config.get("backend_url"),
        **llm_kwargs,
    ).get_llm()
    messages = [
        SystemMessage(
            content=(
                "你是股票研究输入解析器。\n"
                "你的任务是从用户自然语言中尽量提取以下字段，并只输出 JSON：\n"
                "company_name: 股票名称或公司简称，若无法确定则为 null\n"
                "ticker: A股 ts_code，例如 600519.SH 或 000001.SZ，若无法确定则为 null\n"
                "analysis_date: YYYY-MM-DD，若用户未指定则为 null\n"
                "query_intent: 用户的研究意图简述\n"
                "parse_confidence: 0 到 1 之间的小数\n"
                "不要编造股票代码或日期。若无法从自然语言中确定，就返回 null。"
            )
        ),
        HumanMessage(content=f"用户输入：{query_text}"),
    ]
    response = llm.invoke(messages)
    content = response.content if isinstance(response.content, str) else str(response.content)
    try:
        return json.loads(_strip_json_block(content))
    except Exception:
        return {
            "company_name": None,
            "ticker": None,
            "analysis_date": None,
            "query_intent": query_text.strip(),
            "parse_confidence": 0.0,
        }


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None
    return text


def _fallback_extract_candidate(query_text: str) -> dict[str, Any]:
    text = query_text.strip()
    ts_code_match = re.search(r"\b(\d{6}\.(?:SH|SZ))\b", text, flags=re.IGNORECASE)
    if ts_code_match:
        return {
            "company_name": None,
            "ticker": ts_code_match.group(1).upper(),
            "analysis_date": None,
            "query_intent": text,
            "parse_confidence": 0.45,
        }

    digit_match = re.search(r"\b(\d{6})\b", text)
    if digit_match:
        return {
            "company_name": None,
            "ticker": digit_match.group(1),
            "analysis_date": None,
            "query_intent": text,
            "parse_confidence": 0.4,
        }

    candidate = re.sub(r"^(帮我|请|想|我要|看看|分析|研究一下|研究|帮忙)?", "", text).strip(" ，。,.")
    return {
        "company_name": candidate or None,
        "ticker": None,
        "analysis_date": None,
        "query_intent": text,
        "parse_confidence": 0.25 if candidate else 0.0,
    }


def _lookup_by_name(company_name: str) -> tuple[str | None, str | None, bool]:
    pro = _require_tushare()
    basic = _read_or_query(
        "stock_basic_active_lookup",
        {"list_status": "L"},
        lambda: pro.stock_basic(list_status="L", fields="ts_code,symbol,name"),
    )
    if basic.empty:
        return None, None, False

    names = basic["name"].astype(str).str.strip()
    exact = basic[names == company_name.strip()]
    if len(exact) == 1:
        row = exact.iloc[0]
        return str(row.get("ts_code") or "").upper() or None, str(row.get("name") or "").strip() or None, True
    if len(exact) > 1:
        return None, company_name, False

    contains = basic[names.str.contains(re.escape(company_name.strip()), na=False)]
    if len(contains) == 1:
        row = contains.iloc[0]
        return str(row.get("ts_code") or "").upper() or None, str(row.get("name") or "").strip() or None, True
    return None, company_name, False


def _lookup_by_ticker(ticker: str) -> tuple[str | None, str | None, bool]:
    try:
        ts_code = _normalize_symbol(ticker)
    except Exception:
        return None, None, False
    pro = _require_tushare()
    basic = _read_or_query(
        "stock_basic_by_ts_code",
        {"ts_code": ts_code},
        lambda: pro.stock_basic(ts_code=ts_code, fields="ts_code,symbol,name"),
    )
    if basic.empty:
        return ts_code, None, False
    row = basic.iloc[0]
    return ts_code, str(row.get("name") or "").strip() or None, True


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_research_query(config: dict[str, Any], query_text: str, analysis_date: str | None = None) -> dict[str, Any]:
    try:
        parsed = _call_parse_llm(config, query_text)
    except Exception:
        parsed = _fallback_extract_candidate(query_text)
    company_name = _clean_text(parsed.get("company_name"))
    ticker = _clean_text(parsed.get("ticker"))
    normalized_date = _normalize_date(analysis_date) or _normalize_date(_clean_text(parsed.get("analysis_date"))) or _default_analysis_date()
    query_intent = _clean_text(parsed.get("query_intent")) or query_text.strip()
    try:
        parse_confidence = float(parsed.get("parse_confidence") or 0.0)
    except Exception:
        parse_confidence = 0.0

    resolved_ticker: str | None = None
    resolved_company_name: str | None = None
    resolved = False

    try:
        if ticker and not company_name:
            resolved_ticker, resolved_company_name, resolved = _lookup_by_ticker(ticker)
        elif company_name and not ticker:
            resolved_ticker, resolved_company_name, resolved = _lookup_by_name(company_name)
        elif ticker and company_name:
            resolved_ticker, looked_up_name, ticker_ok = _lookup_by_ticker(ticker)
            if ticker_ok and looked_up_name and looked_up_name == company_name:
                resolved_company_name = looked_up_name
                resolved = True
            else:
                resolved_company_name = company_name
                resolved = False
        else:
            resolved = False
    except Exception:
        # Tushare may be unavailable during local development; degrade to confirm-first mode.
        resolved_ticker = ticker
        resolved_company_name = company_name
        resolved = False

    final_ticker = resolved_ticker or ticker
    final_company_name = resolved_company_name or company_name
    needs_confirmation = not bool(final_ticker and final_company_name and resolved)

    clarification_question: str | None = None
    if needs_confirmation:
        if ticker and not company_name:
            clarification_question = f"我识别到股票代码可能是 {ticker}，但还不能确认公司名称，请确认是否继续。"
        elif company_name and not ticker:
            clarification_question = f"我识别到你想研究“{company_name}”，但还不能唯一确认股票代码，请补充代码或更精确的公司名称。"
        elif ticker and company_name:
            clarification_question = f"我识别到代码 {ticker} 和公司“{company_name}”，但两者校验未通过，请确认正确的股票代码或公司名称。"
        else:
            clarification_question = "我还不能确定你要研究的股票，请补充股票代码或更明确的公司名称。"

    return {
        "query_text": query_text.strip(),
        "ticker": final_ticker,
        "company_name": final_company_name,
        "analysis_date": normalized_date,
        "query_intent": query_intent,
        "parse_confidence": round(max(0.0, min(parse_confidence, 1.0)), 3),
        "needs_confirmation": needs_confirmation,
        "clarification_question": clarification_question,
    }
