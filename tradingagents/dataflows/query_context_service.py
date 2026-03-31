from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .tushare_provider import _normalize_symbol, _read_or_query, _require_tushare


_THS_INDEX_MAPPING_PATH = Path(__file__).resolve().parent / "data_cache" / "ths_index_mapping.json"
_THS_NOISE_PATTERNS = (
    "同花顺",
    "全A",
    "沪深",
    "主板",
    "大盘",
    "中盘",
    "小盘",
    "沪股通",
    "陆股通",
    "低估值",
    "高估值",
    "激进投资",
    "稳健投资",
    "成长投资",
    "价值投资",
    "加权",
    "等权",
    "样本股",
    "成份股",
    "成分股",
    "新高",
    "新低",
    "重仓",
    "高动量",
    "高盈利",
    "低波动",
)


def _safe_query(endpoint: str, params: dict[str, Any], query_func) -> pd.DataFrame:
    try:
        return _read_or_query(endpoint, params, query_func)
    except Exception:
        return pd.DataFrame()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def _stringify_unique(values: list[Any], limit: int = 12) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _load_ths_index_mapping() -> dict[str, dict[str, str]]:
    if not _THS_INDEX_MAPPING_PATH.exists():
        return {}
    try:
        data = json.loads(_THS_INDEX_MAPPING_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _filter_ths_concepts(values: list[str], limit: int = 12) -> list[str]:
    filtered: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        if any(pattern in text for pattern in _THS_NOISE_PATTERNS):
            continue
        filtered.append(text)
    return _stringify_unique(filtered, limit=limit)


def _fetch_stock_company(ts_code: str) -> dict[str, Any]:
    pro = _require_tushare()
    df = _safe_query(
        "stock_company",
        {"ts_code": ts_code},
        lambda: pro.stock_company(ts_code=ts_code),
    )
    if df.empty:
        return {}

    row = df.head(1).iloc[0].to_dict()
    return {
        "com_name": _clean_text(row.get("com_name") or row.get("fullname") or row.get("name")),
        "chairman": _clean_text(row.get("chairman")),
        "manager": _clean_text(row.get("manager")),
        "province": _clean_text(row.get("province")),
        "city": _clean_text(row.get("city")),
        "website": _clean_text(row.get("website")),
        "email": _clean_text(row.get("email")),
        "employees": _clean_text(row.get("employees")),
        "main_business": _clean_text(
            row.get("main_business")
            or row.get("business_scope")
            or row.get("scope")
        ),
        "introduction": _clean_text(row.get("introduction") or row.get("intro")),
    }


def _fetch_main_business_items(ts_code: str, analysis_date: str, limit: int = 8) -> list[str]:
    pro = _require_tushare()
    period = datetime.strptime(analysis_date, "%Y-%m-%d").strftime("%Y1231")
    candidates: list[pd.DataFrame] = []
    for params, query_func in [
        (
            {"ts_code": ts_code, "period": period, "type": "P"},
            lambda: pro.fina_mainbz(ts_code=ts_code, period=period, type="P"),
        ),
        (
            {"ts_code": ts_code, "type": "P"},
            lambda: pro.fina_mainbz(ts_code=ts_code, type="P"),
        ),
        (
            {"ts_code": ts_code},
            lambda: pro.fina_mainbz(ts_code=ts_code),
        ),
    ]:
        df = _safe_query("fina_mainbz", params, query_func)
        if not df.empty:
            candidates.append(df)
            break

    if not candidates:
        return []

    df = candidates[0].copy()
    if "end_date" in df.columns:
        df["end_date"] = df["end_date"].astype(str)
        df = df.sort_values("end_date", ascending=False)
    if "bz_sales" in df.columns:
        df["bz_sales"] = pd.to_numeric(df["bz_sales"], errors="coerce")
        df = df.sort_values("bz_sales", ascending=False, na_position="last")

    values = df.get("bz_item")
    if values is None:
        return []
    return _stringify_unique(values.tolist(), limit=limit)


def _fetch_ths_concepts(ts_code: str, limit: int = 12) -> list[str]:
    pro = _require_tushare()
    member = _safe_query(
        "ths_member",
        {"ts_code": ts_code},
        lambda: pro.ths_member(ts_code=ts_code),
    )
    if member.empty:
        member = _safe_query(
            "ths_member",
            {"con_code": ts_code},
            lambda: pro.ths_member(con_code=ts_code),
        )
    if member.empty:
        return []

    mapping = _load_ths_index_mapping()
    values: list[str] = []
    codes: list[str] = []
    for _, row in member.iterrows():
        row_dict = row.to_dict()
        code = _clean_text(row_dict.get("ts_code") or row_dict.get("index_code"))
        if code:
            codes.append(code)
            mapped = mapping.get(code) or {}
            if not isinstance(mapped, dict):
                mapped = {}
            values.append(_clean_text(mapped.get("name")) or code)

    return {
        "codes": _stringify_unique(codes, limit=limit),
        "names": _filter_ths_concepts(values, limit=limit),
    }


def _fetch_index_memberships(ts_code: str, analysis_date: str, limit: int = 12) -> list[str]:
    pro = _require_tushare()
    start_date = (datetime.strptime(analysis_date, "%Y-%m-%d") - timedelta(days=3650)).strftime("%Y%m%d")
    end_date = datetime.strptime(analysis_date, "%Y-%m-%d").strftime("%Y%m%d")
    df = _safe_query(
        "index_member_all",
        {"ts_code": ts_code, "is_new": "Y"},
        lambda: pro.index_member_all(ts_code=ts_code, is_new="Y"),
    )
    if df.empty:
        df = _safe_query(
            "index_member_all",
            {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
            lambda: pro.index_member_all(ts_code=ts_code, start_date=start_date, end_date=end_date),
        )
    if df.empty:
        return []

    values: list[str] = []
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        values.extend(
            [
                _clean_text(row_dict.get("l1_name")),
                _clean_text(row_dict.get("l2_name")),
                _clean_text(row_dict.get("l3_name")),
            ]
        )

    return _stringify_unique(values, limit=limit)


def build_event_query_context(
    ticker: str,
    analysis_date: str,
    company_name: str = "",
    industry: str = "",
    company_type: str = "",
) -> dict[str, Any]:
    ts_code = _normalize_symbol(ticker)
    stock_company = _fetch_stock_company(ts_code)
    main_business_items = _fetch_main_business_items(ts_code, analysis_date)
    ths_member = _fetch_ths_concepts(ts_code)
    ths_member_codes = ths_member.get("codes", [])
    ths_concepts = ths_member.get("names", [])
    index_memberships = _fetch_index_memberships(ts_code, analysis_date)

    intro = _clean_text(stock_company.get("introduction"))
    intro = intro[:280] if intro else ""
    main_business = _clean_text(stock_company.get("main_business"))
    main_business = main_business[:280] if main_business else ""

    search_aliases = _stringify_unique(
        [
            company_name,
            stock_company.get("com_name"),
            *main_business_items[:4],
            *index_memberships[:4],
        ],
        limit=12,
    )

    return {
        "ticker": ts_code,
        "analysis_date": analysis_date,
        "company_name": company_name,
        "industry": industry,
        "company_type": company_type,
        "stock_company": stock_company,
        "company_intro": intro,
        "main_business": main_business,
        "main_business_items": main_business_items,
        "ths_member_codes": ths_member_codes,
        "ths_concepts": ths_concepts,
        "index_memberships": index_memberships,
        "search_aliases": search_aliases,
    }
