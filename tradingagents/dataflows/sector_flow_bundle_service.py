from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .fundamental_bundle_service import _detect_company_profile
from .technical_bundle_service import normalize_trade_date
from .tushare_provider import (
    _normalize_symbol,
    _query_daily_bundle,
    _read_or_query,
    _require_tushare,
)


DEFAULT_LOOKBACK_TRADING_DAYS = 60


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Any, digits: int = 6) -> float | None:
    number = _safe_float(value)
    return None if number is None else round(number, digits)


def _fetch_stock_basic(ts_code: str) -> pd.Series:
    pro = _require_tushare()
    df = _read_or_query(
        "stock_basic_single",
        {"ts_code": ts_code},
        lambda: pro.stock_basic(ts_code=ts_code),
    )
    if df.empty:
        return pd.Series(dtype=object)
    return df.head(1).iloc[0]


def _fetch_all_active_stocks() -> pd.DataFrame:
    pro = _require_tushare()
    return _read_or_query(
        "stock_basic_active",
        {"list_status": "L"},
        lambda: pro.stock_basic(list_status="L"),
    )


def _fetch_sw_membership_all() -> pd.DataFrame:
    pro = _require_tushare()
    return _read_or_query(
        "index_member_all",
        {"is_new": "Y"},
        lambda: pro.index_member_all(is_new="Y"),
    )


def _resolve_sector_membership(ts_code: str, basic_row: pd.Series) -> dict[str, Any]:
    membership = _fetch_sw_membership_all()
    stock_rows = membership[membership["ts_code"] == ts_code]
    if not stock_rows.empty:
        row = stock_rows.iloc[0]
        if pd.notna(row.get("l2_code")) and pd.notna(row.get("l2_name")):
            return {
                "sector_code": row.get("l2_code"),
                "sector_name": row.get("l2_name"),
                "sector_level": "l2",
                "sector_members": membership[membership["l2_code"] == row.get("l2_code")].copy(),
            }
        return {
            "sector_code": row.get("l1_code"),
            "sector_name": row.get("l1_name"),
            "sector_level": "l1",
            "sector_members": membership[membership["l1_code"] == row.get("l1_code")].copy(),
        }

    industry = basic_row.get("industry")
    all_stocks = _fetch_all_active_stocks()
    peers = all_stocks[all_stocks["industry"] == industry].copy()
    return {
        "sector_code": None,
        "sector_name": industry,
        "sector_level": "stock_basic_industry",
        "sector_members": peers,
    }


def _fetch_sector_series(sector_code: str | None, effective_date: str, lookback_trading_days: int) -> pd.DataFrame:
    if not sector_code:
        return pd.DataFrame()

    pro = _require_tushare()
    effective_dt = datetime.strptime(effective_date, "%Y-%m-%d")
    start_date = (effective_dt - timedelta(days=max(lookback_trading_days * 2, 120))).strftime("%Y%m%d")
    end_date = effective_dt.strftime("%Y%m%d")
    df = _read_or_query(
        "sw_daily",
        {"ts_code": sector_code, "start_date": start_date, "end_date": end_date},
        lambda: pro.sw_daily(ts_code=sector_code, start_date=start_date, end_date=end_date),
    )
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    return df.sort_values("trade_date").tail(lookback_trading_days).reset_index(drop=True)


def _fetch_trade_days(effective_date: str, count: int = 5, exchange: str = "SSE") -> list[str]:
    pro = _require_tushare()
    target = datetime.strptime(effective_date, "%Y-%m-%d")
    start = (target - timedelta(days=40)).strftime("%Y%m%d")
    end = target.strftime("%Y%m%d")
    calendar = pro.trade_cal(exchange=exchange, start_date=start, end_date=end)
    if calendar.empty:
        return [effective_date]
    calendar["cal_date"] = pd.to_datetime(calendar["cal_date"], format="%Y%m%d")
    open_days = (
        calendar[(calendar["cal_date"] <= target) & (calendar["is_open"] == 1)]
        .sort_values("cal_date")
        .tail(count)
    )
    return [day.strftime("%Y-%m-%d") for day in open_days["cal_date"].tolist()]


def _fetch_cross_section(endpoint: str, trade_date: str) -> pd.DataFrame:
    pro = _require_tushare()
    trade_date_compact = trade_date.replace("-", "")
    endpoint_func = getattr(pro, endpoint)
    return _read_or_query(
        endpoint,
        {"trade_date": trade_date_compact},
        lambda: endpoint_func(trade_date=trade_date_compact),
    )


def _build_sector_cross_section(
    sector_members: pd.DataFrame,
    effective_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    peer_codes = set(sector_members["ts_code"].dropna().tolist())
    if not peer_codes:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty

    daily = _fetch_cross_section("daily", effective_date)
    daily_basic = _fetch_cross_section("daily_basic", effective_date)
    moneyflow = _fetch_cross_section("moneyflow", effective_date)
    limit_list = _fetch_cross_section("limit_list_d", effective_date)
    top_inst = _fetch_cross_section("top_inst", effective_date)

    daily = daily[daily["ts_code"].isin(peer_codes)].copy()
    daily_basic = daily_basic[daily_basic["ts_code"].isin(peer_codes)].copy()
    moneyflow = moneyflow[moneyflow["ts_code"].isin(peer_codes)].copy()
    limit_list = limit_list[limit_list["ts_code"].isin(peer_codes)].copy() if not limit_list.empty else limit_list
    top_inst = top_inst[top_inst["ts_code"].isin(peer_codes)].copy() if not top_inst.empty else top_inst

    merged = sector_members[["ts_code", "name"]].drop_duplicates().merge(
        daily, on="ts_code", how="left"
    )
    merged = merged.merge(
        daily_basic[["ts_code", "turnover_rate", "turnover_rate_f", "volume_ratio", "circ_mv", "total_mv"]],
        on="ts_code",
        how="left",
    )
    moneyflow_columns = ["ts_code", "net_mf_amount", "buy_lg_amount", "sell_lg_amount", "buy_elg_amount", "sell_elg_amount"]
    available_moneyflow_columns = [col for col in moneyflow_columns if col in moneyflow.columns]
    if available_moneyflow_columns:
        merged = merged.merge(moneyflow[available_moneyflow_columns], on="ts_code", how="left")

    merged["pct_chg"] = pd.to_numeric(merged.get("pct_chg"), errors="coerce")
    merged["amount"] = pd.to_numeric(merged.get("amount"), errors="coerce")
    merged["turnover_rate"] = pd.to_numeric(merged.get("turnover_rate"), errors="coerce")
    merged["volume_ratio"] = pd.to_numeric(merged.get("volume_ratio"), errors="coerce")
    merged["circ_mv"] = pd.to_numeric(merged.get("circ_mv"), errors="coerce")
    merged["net_mf_amount"] = pd.to_numeric(merged.get("net_mf_amount"), errors="coerce")
    return merged, daily, limit_list, top_inst, moneyflow


def _percentile_rank(series: pd.Series, value: float | None) -> float | None:
    if value is None:
        return None
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        return None
    return round(float((valid <= value).mean()), 6)


def _compute_sector_snapshot(
    sector_series: pd.DataFrame,
    peer_snapshot: pd.DataFrame,
    limit_list: pd.DataFrame,
    top_inst: pd.DataFrame,
) -> dict[str, Any]:
    latest_sector = sector_series.iloc[-1] if not sector_series.empty else pd.Series(dtype=object)
    prev_sector = sector_series.iloc[-2] if len(sector_series) >= 2 else latest_sector

    sector_amount = _safe_float(latest_sector.get("amount"))
    prev_amount = _safe_float(prev_sector.get("amount"))
    sector_amount_change = None
    if sector_amount is not None and prev_amount not in (None, 0):
        sector_amount_change = round(sector_amount / prev_amount - 1, 6)

    sector_volume = _safe_float(latest_sector.get("vol"))
    prev_volume = _safe_float(prev_sector.get("vol"))
    sector_volume_change = None
    if sector_volume is not None and prev_volume not in (None, 0):
        sector_volume_change = round(sector_volume / prev_volume - 1, 6)

    breadth = None
    if not peer_snapshot.empty and peer_snapshot["pct_chg"].notna().any():
        breadth = round(float((peer_snapshot["pct_chg"] > 0).mean()), 6)

    return {
        "sector_pct_chg": _round_or_none(latest_sector.get("pct_change")),
        "sector_volume_change": sector_volume_change,
        "sector_amount_change": sector_amount_change,
        "sector_breadth_up_ratio": breadth,
        "sector_limit_up_count": 0 if limit_list.empty else int((limit_list["limit"] == "U").sum()),
        "sector_limit_down_count": 0 if limit_list.empty else int((limit_list["limit"] == "D").sum()),
        "sector_top_inst_count": 0 if top_inst.empty else int(top_inst["ts_code"].nunique()),
    }


def _compute_theme_activity(peer_snapshot: pd.DataFrame, limit_list: pd.DataFrame) -> dict[str, Any]:
    leaders = []
    if not peer_snapshot.empty:
        ranked = peer_snapshot.sort_values(["pct_chg", "net_mf_amount"], ascending=False)
        leaders = ranked["name"].dropna().head(5).tolist()

    limit_up_count = 0 if limit_list.empty else int((limit_list["limit"] == "U").sum())
    breadth = None
    if not peer_snapshot.empty and peer_snapshot["pct_chg"].notna().any():
        breadth = float((peer_snapshot["pct_chg"] > 0).mean())

    if limit_up_count >= 2 and breadth is not None and breadth >= 0.6:
        expansion = "broadening"
    elif limit_up_count >= 1 or (breadth is not None and breadth >= 0.5):
        expansion = "contained"
    else:
        expansion = "narrow"

    if breadth is None:
        dispersion = "unknown"
    elif breadth >= 0.7:
        dispersion = "broad_participation"
    elif breadth >= 0.45:
        dispersion = "mixed_participation"
    else:
        dispersion = "thin_participation"

    leader_confirmation = "confirmed" if leaders and limit_up_count >= 1 else "unconfirmed"
    return {
        "leader_stock_names": leaders,
        "leader_confirmation": leader_confirmation,
        "theme_expansion": expansion,
        "theme_dispersion": dispersion,
    }


def _compute_target_snapshot(target_row: pd.Series, top_inst: pd.DataFrame, limit_list: pd.DataFrame) -> dict[str, Any]:
    ts_code = target_row.get("ts_code")
    top_inst_row_count = 0 if top_inst.empty else int((top_inst["ts_code"] == ts_code).sum())
    limit_state = None
    if not limit_list.empty:
        matched = limit_list[limit_list["ts_code"] == ts_code]
        if not matched.empty:
            limit_state = matched.iloc[0].get("limit")

    return {
        "close": _round_or_none(target_row.get("close"), 4),
        "pct_chg": _round_or_none(target_row.get("pct_chg")),
        "volume": _round_or_none(target_row.get("vol"), 4),
        "amount": _round_or_none(target_row.get("amount"), 4),
        "turnover_rate": _round_or_none(target_row.get("turnover_rate")),
        "volume_ratio": _round_or_none(target_row.get("volume_ratio")),
        "circ_mv": _round_or_none(target_row.get("circ_mv"), 4),
        "net_mf_amount": _round_or_none(target_row.get("net_mf_amount"), 4),
        "top_inst_row_count": top_inst_row_count,
        "limit_state": limit_state,
    }


def _compute_relative_position(target_row: pd.Series, peer_snapshot: pd.DataFrame) -> dict[str, Any]:
    pct_chg = _safe_float(target_row.get("pct_chg"))
    turnover_rate = _safe_float(target_row.get("turnover_rate"))
    net_mf_amount = _safe_float(target_row.get("net_mf_amount"))
    volume_ratio = _safe_float(target_row.get("volume_ratio"))
    return {
        "pct_chg_percentile": _percentile_rank(peer_snapshot.get("pct_chg", pd.Series(dtype=float)), pct_chg),
        "turnover_percentile": _percentile_rank(peer_snapshot.get("turnover_rate", pd.Series(dtype=float)), turnover_rate),
        "moneyflow_percentile": _percentile_rank(peer_snapshot.get("net_mf_amount", pd.Series(dtype=float)), net_mf_amount),
        "volume_ratio_percentile": _percentile_rank(peer_snapshot.get("volume_ratio", pd.Series(dtype=float)), volume_ratio),
    }


def _compute_flow_features(target_df: pd.DataFrame, target_row: pd.Series, sector_series: pd.DataFrame) -> dict[str, Any]:
    latest = target_df.iloc[-1]
    volume = _safe_float(latest.get("vol"))
    amount = _safe_float(latest.get("amount"))
    turnover_rate = _safe_float(latest.get("turnover_rate"))
    net_mf_amount = _safe_float(latest.get("net_mf_amount"))
    volume_ma20 = target_df["vol"].tail(20).mean() if len(target_df) >= 20 else None
    amount_ma20 = target_df["amount"].tail(20).mean() if len(target_df) >= 20 else None

    turnover_series = pd.to_numeric(target_df.get("turnover_rate"), errors="coerce").dropna()
    net_mf_series = pd.to_numeric(target_df.get("net_mf_amount"), errors="coerce").dropna()

    moneyflow_positive_3d = None
    if len(net_mf_series) >= 3:
        moneyflow_positive_3d = int((net_mf_series.tail(3) > 0).sum())
    moneyflow_positive_5d = None
    if len(net_mf_series) >= 5:
        moneyflow_positive_5d = int((net_mf_series.tail(5) > 0).sum())

    sector_amount_change_5d = None
    if len(sector_series) >= 6:
        latest_amount = _safe_float(sector_series.iloc[-1].get("amount"))
        base_amount = _safe_float(sector_series.iloc[-6].get("amount"))
        if latest_amount is not None and base_amount not in (None, 0):
            sector_amount_change_5d = round(latest_amount / base_amount - 1, 6)

    crowding_proxy = 0.0
    if turnover_series.size:
        current_turnover_pct = float((turnover_series <= turnover_rate).mean()) if turnover_rate is not None else 0.0
        crowding_proxy += current_turnover_pct
    volume_ratio_value = _safe_float(target_row.get("volume_ratio"))
    if volume_ratio_value is not None:
        crowding_proxy += min(volume_ratio_value / 3, 1.0)
    crowding_proxy = round(crowding_proxy / 2, 6) if crowding_proxy else None

    return {
        "volume_vs_ma20": None if volume in (None,) or volume_ma20 in (None, 0) else round(volume / volume_ma20 - 1, 6),
        "amount_vs_ma20": None if amount in (None,) or amount_ma20 in (None, 0) else round(amount / amount_ma20 - 1, 6),
        "turnover_percentile_20d": None if turnover_series.empty or turnover_rate is None else round(float((turnover_series.tail(20) <= turnover_rate).mean()), 6),
        "turnover_percentile_60d": None if turnover_series.empty or turnover_rate is None else round(float((turnover_series <= turnover_rate).mean()), 6),
        "moneyflow_persistence_3d": moneyflow_positive_3d,
        "moneyflow_persistence_5d": moneyflow_positive_5d,
        "sector_amount_change_5d": sector_amount_change_5d,
        "crowding_proxy": crowding_proxy,
        "net_mf_amount": _round_or_none(net_mf_amount, 4),
        "turnover_rate": _round_or_none(turnover_rate),
    }


def _build_sector_flow_compact_signals(
    sector_snapshot: dict[str, Any],
    target_snapshot: dict[str, Any],
    relative_position: dict[str, Any],
    flow_features: dict[str, Any],
    theme_activity: dict[str, Any],
) -> dict[str, str]:
    sector_pct = _safe_float(sector_snapshot.get("sector_pct_chg"))
    breadth = _safe_float(sector_snapshot.get("sector_breadth_up_ratio"))
    sector_limit_up_count = int(sector_snapshot.get("sector_limit_up_count") or 0)
    sector_amount_change = _safe_float(sector_snapshot.get("sector_amount_change"))
    stock_turnover_pct = _safe_float(relative_position.get("turnover_percentile"))
    stock_pct_rank = _safe_float(relative_position.get("pct_chg_percentile"))
    stock_mf_rank = _safe_float(relative_position.get("moneyflow_percentile"))
    crowding_proxy = _safe_float(flow_features.get("crowding_proxy"))
    mf_3d = flow_features.get("moneyflow_persistence_3d")
    mf_5d = flow_features.get("moneyflow_persistence_5d")

    if sector_pct is not None and breadth is not None and (sector_pct >= 1.0 or breadth >= 0.65):
        theme_strength = "strong"
    elif sector_pct is not None and breadth is not None and (sector_pct >= 0 or breadth >= 0.5):
        theme_strength = "moderate"
    else:
        theme_strength = "weak"

    if (sector_amount_change is not None and sector_amount_change >= 0.2) or sector_limit_up_count >= 2:
        theme_heat = "hot"
    elif (sector_amount_change is not None and sector_amount_change >= 0.05) or sector_limit_up_count >= 1:
        theme_heat = "warm"
    else:
        theme_heat = "cold"

    if (crowding_proxy is not None and crowding_proxy >= 0.75) or (stock_turnover_pct is not None and stock_turnover_pct >= 0.85):
        crowding_level = "high"
    elif (crowding_proxy is not None and crowding_proxy >= 0.45) or (stock_turnover_pct is not None and stock_turnover_pct >= 0.6):
        crowding_level = "medium"
    else:
        crowding_level = "low"

    if (stock_pct_rank is not None and stock_pct_rank >= 0.85) and (stock_mf_rank is not None and stock_mf_rank >= 0.75):
        stock_role = "leader"
    elif (stock_pct_rank is not None and stock_pct_rank >= 0.6) and (stock_mf_rank is not None and stock_mf_rank >= 0.5):
        stock_role = "core_follower"
    elif (stock_pct_rank is not None and stock_pct_rank <= 0.3) and (stock_mf_rank is not None and stock_mf_rank <= 0.4):
        stock_role = "lagging"
    else:
        stock_role = "peripheral"

    if (mf_5d is not None and mf_5d >= 4) or (mf_3d is not None and mf_3d >= 3):
        persistence = "persistent"
    elif (mf_5d is not None and mf_5d <= 1) or (mf_3d is not None and mf_3d == 0):
        persistence = "fading"
    else:
        persistence = "unstable"

    if theme_strength == "strong" and theme_heat in {"hot", "warm"}:
        rotation_state = "strengthening"
    elif theme_strength == "weak" and theme_heat == "cold":
        rotation_state = "rotating_out"
    else:
        rotation_state = "stable"

    return {
        "theme_strength": theme_strength,
        "theme_heat": theme_heat,
        "crowding_level": crowding_level,
        "stock_role": stock_role,
        "flow_persistence": persistence,
        "rotation_state": rotation_state,
    }


def _serialize_sector_series(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        records.append(
            {
                "trade_date": row["trade_date"].strftime("%Y-%m-%d"),
                "close": _round_or_none(row.get("close"), 4),
                "pct_change": _round_or_none(row.get("pct_change")),
                "amount": _round_or_none(row.get("amount"), 4),
                "vol": _round_or_none(row.get("vol"), 4),
            }
        )
    return records


def _serialize_peer_rankings(peer_snapshot: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    if peer_snapshot.empty:
        return []
    ranked = peer_snapshot.sort_values(["pct_chg", "net_mf_amount"], ascending=False).head(limit)
    results: list[dict[str, Any]] = []
    for _, row in ranked.iterrows():
        results.append(
            {
                "ts_code": row.get("ts_code"),
                "name": row.get("name"),
                "pct_chg": _round_or_none(row.get("pct_chg")),
                "turnover_rate": _round_or_none(row.get("turnover_rate")),
                "net_mf_amount": _round_or_none(row.get("net_mf_amount"), 4),
            }
        )
    return results


def build_sector_flow_data_bundle(
    ticker: str,
    analysis_date: str,
    lookback_trading_days: int = DEFAULT_LOOKBACK_TRADING_DAYS,
) -> dict[str, Any]:
    ts_code = _normalize_symbol(ticker)
    normalized = normalize_trade_date(analysis_date)
    effective_date = normalized["effective_trade_date"]

    basic_row = _fetch_stock_basic(ts_code)
    company_profile = _detect_company_profile(basic_row.get("industry"))
    sector_meta = _resolve_sector_membership(ts_code, basic_row)
    sector_members = sector_meta["sector_members"]

    target_df = _query_daily_bundle(
        ts_code,
        (datetime.strptime(effective_date, "%Y-%m-%d") - timedelta(days=max(lookback_trading_days * 2, 120))).strftime("%Y%m%d"),
        datetime.strptime(effective_date, "%Y-%m-%d").strftime("%Y%m%d"),
    )
    if target_df.empty:
        raise RuntimeError(f"No sector flow data found for {ts_code} up to {effective_date}")
    target_df = target_df[target_df["trade_date"] <= pd.to_datetime(effective_date)].tail(lookback_trading_days).reset_index(drop=True)
    target_row = target_df.iloc[-1]

    sector_series = _fetch_sector_series(sector_meta["sector_code"], effective_date, lookback_trading_days)
    peer_snapshot, _, limit_list, top_inst, _ = _build_sector_cross_section(sector_members, effective_date)
    if peer_snapshot.empty:
        raise RuntimeError(f"No peer snapshot available for {ts_code} on {effective_date}")
    target_snapshot_row = peer_snapshot[peer_snapshot["ts_code"] == ts_code]
    if target_snapshot_row.empty:
        target_snapshot_row = pd.DataFrame([target_row])
    target_snapshot_row = target_snapshot_row.iloc[0]

    sector_snapshot = _compute_sector_snapshot(sector_series, peer_snapshot, limit_list, top_inst)
    theme_activity = _compute_theme_activity(peer_snapshot, limit_list)
    stock_snapshot = _compute_target_snapshot(target_snapshot_row, top_inst, limit_list)
    relative_position = _compute_relative_position(target_snapshot_row, peer_snapshot)
    flow_features = _compute_flow_features(target_df, target_snapshot_row, sector_series)
    compact_signals = _build_sector_flow_compact_signals(
        sector_snapshot=sector_snapshot,
        target_snapshot=stock_snapshot,
        relative_position=relative_position,
        flow_features=flow_features,
        theme_activity=theme_activity,
    )

    return {
        "ticker": ts_code,
        "requested_date": normalized["requested_date"],
        "effective_trade_date": effective_date,
        "meta": {
            "name": basic_row.get("name"),
            "industry": basic_row.get("industry"),
            "market": basic_row.get("market"),
            "company_type": company_profile.get("company_type"),
            "sector_index": sector_meta.get("sector_code"),
            "sector_name": sector_meta.get("sector_name"),
            "sector_level": sector_meta.get("sector_level"),
            "sector_member_count": int(sector_members["ts_code"].nunique()) if not sector_members.empty else 0,
        },
        "stock_snapshot": stock_snapshot,
        "sector_snapshot": sector_snapshot,
        "relative_position": relative_position,
        "theme_activity": theme_activity,
        "flow_features": flow_features,
        "sector_flow_compact_signals": compact_signals,
        "sector_series": _serialize_sector_series(sector_series),
        "peer_rankings": _serialize_peer_rankings(peer_snapshot),
        "data_quality": {
            "is_trade_date_aligned": normalized["is_trade_date_aligned"],
            "missing_fields": [],
            "source": "tushare",
        },
    }


def get_sector_peer_context(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_sector_flow_data_bundle(ticker=ticker, analysis_date=analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "meta": bundle["meta"],
        "peer_rankings": bundle["peer_rankings"],
        "relative_position": bundle["relative_position"],
    }


def get_sector_activity_context(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_sector_flow_data_bundle(ticker=ticker, analysis_date=analysis_date)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "sector_snapshot": bundle["sector_snapshot"],
        "theme_activity": bundle["theme_activity"],
        "sector_series": bundle["sector_series"],
        "sector_flow_compact_signals": bundle["sector_flow_compact_signals"],
    }
