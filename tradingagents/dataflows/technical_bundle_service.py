from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .tushare_provider import (
    _compute_indicators,
    _normalize_symbol,
    _query_daily_bundle,
    _read_or_query,
    _require_tushare,
)


DEFAULT_BENCHMARK = "000300.SH"
DEFAULT_LOOKBACK_TRADING_DAYS = 90


def normalize_trade_date(requested_date: str, exchange: str = "SSE") -> dict[str, str]:
    pro = _require_tushare()
    target = datetime.strptime(requested_date, "%Y-%m-%d")
    start = (target - timedelta(days=30)).strftime("%Y%m%d")
    end = target.strftime("%Y%m%d")
    calendar = pro.trade_cal(exchange=exchange, start_date=start, end_date=end)
    if calendar.empty:
        raise RuntimeError(f"No trade calendar data found for exchange={exchange}")

    calendar["cal_date"] = pd.to_datetime(calendar["cal_date"], format="%Y%m%d")
    open_days = calendar[(calendar["cal_date"] <= target) & (calendar["is_open"] == 1)]
    if open_days.empty:
        raise ValueError(f"No open trading day found on or before {requested_date}")

    effective = open_days.sort_values("cal_date").iloc[-1]["cal_date"].strftime("%Y-%m-%d")
    return {
        "requested_date": requested_date,
        "effective_trade_date": effective,
        "exchange": exchange,
        "is_trade_date_aligned": effective == requested_date,
    }


def _fetch_security_meta(ts_code: str) -> dict[str, Any]:
    pro = _require_tushare()
    basic = _read_or_query(
        "stock_basic",
        {"ts_code": ts_code},
        lambda: pro.stock_basic(ts_code=ts_code),
    )
    if basic.empty:
        return {"name": ts_code, "industry": None, "market": None}

    row = basic.head(1).iloc[0]
    return {
        "name": row.get("name"),
        "industry": row.get("industry"),
        "market": row.get("market"),
    }


def _fetch_benchmark_series(index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    pro = _require_tushare()
    params = {"ts_code": index_code, "start_date": start_date, "end_date": end_date}
    df = _read_or_query(
        "index_daily",
        params,
        lambda: pro.index_daily(ts_code=index_code, start_date=start_date, end_date=end_date),
    )
    if df.empty:
        return df

    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    return df.sort_values("trade_date").reset_index(drop=True)


def _compute_relative_strength(
    price_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    windows: tuple[int, ...] = (20, 60),
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    if price_df.empty or benchmark_df.empty:
        for window in windows:
            result[f"vs_benchmark_{window}d"] = None
        return result

    merged = price_df[["trade_date", "close"]].merge(
        benchmark_df[["trade_date", "close"]],
        on="trade_date",
        how="inner",
        suffixes=("_stock", "_benchmark"),
    )
    merged = merged.sort_values("trade_date").reset_index(drop=True)
    if merged.empty:
        for window in windows:
            result[f"vs_benchmark_{window}d"] = None
        return result

    for window in windows:
        if len(merged) <= window:
            result[f"vs_benchmark_{window}d"] = None
            continue
        stock_return = merged["close_stock"].iloc[-1] / merged["close_stock"].iloc[-window - 1] - 1
        benchmark_return = (
            merged["close_benchmark"].iloc[-1] / merged["close_benchmark"].iloc[-window - 1] - 1
        )
        result[f"vs_benchmark_{window}d"] = round(float(stock_return - benchmark_return), 6)
    return result


def _rolling_levels(df: pd.DataFrame, windows: tuple[int, ...] = (20, 60, 90)) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for window in windows:
        if len(df) < window:
            result[f"high_{window}"] = None
            result[f"low_{window}"] = None
            continue
        result[f"high_{window}"] = round(float(df["high"].tail(window).max()), 4)
        result[f"low_{window}"] = round(float(df["low"].tail(window).min()), 4)
    return result


def _latest_indicator_snapshot(df: pd.DataFrame) -> dict[str, float | None]:
    latest = df.iloc[-1]
    fields = {
        "sma_20": df["close"].tail(20).mean() if len(df) >= 20 else None,
        "sma_50": latest.get("close_50_sma"),
        "ema_10": latest.get("close_10_ema"),
        "macd": latest.get("macd"),
        "macd_signal": latest.get("macds"),
        "macd_hist": latest.get("macdh"),
        "rsi_14": latest.get("rsi"),
        "atr_14": latest.get("atr"),
        "boll_mid": latest.get("boll"),
        "boll_upper": latest.get("boll_ub"),
        "boll_lower": latest.get("boll_lb"),
        "vwma_20": latest.get("vwma"),
        "volume_ma_20": df["vol"].tail(20).mean() if len(df) >= 20 else None,
        "mfi_14": latest.get("mfi"),
    }
    normalized = {}
    for key, value in fields.items():
        normalized[key] = None if pd.isna(value) else round(float(value), 6)
    return normalized


def _build_indicator_context(df: pd.DataFrame) -> dict[str, Any]:
    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) >= 2 else latest
    close = float(latest["close"])
    prev_close = float(previous["close"]) if not pd.isna(previous["close"]) else close
    sma_20 = float(df["close"].tail(20).mean()) if len(df) >= 20 else None
    sma_50 = float(latest.get("close_50_sma")) if not pd.isna(latest.get("close_50_sma")) else None
    ema_10 = float(latest.get("close_10_ema")) if not pd.isna(latest.get("close_10_ema")) else None
    atr_14 = float(latest.get("atr")) if not pd.isna(latest.get("atr")) else None
    volume = float(latest["vol"]) if not pd.isna(latest["vol"]) else None
    volume_ma_20 = float(df["vol"].tail(20).mean()) if len(df) >= 20 else None

    def _safe_return(window: int) -> float | None:
        if len(df) <= window:
            return None
        base = float(df["close"].iloc[-window - 1])
        if base == 0:
            return None
        return round(close / base - 1, 6)

    boll_upper = latest.get("boll_ub")
    boll_lower = latest.get("boll_lb")
    boll_position = None
    if not pd.isna(boll_upper) and not pd.isna(boll_lower):
        width = float(boll_upper) - float(boll_lower)
        if width > 0:
            boll_position = round((close - float(boll_lower)) / width, 6)

    return {
        "returns": {
            "1d": None if prev_close == 0 else round(close / prev_close - 1, 6),
            "5d": _safe_return(5),
            "20d": _safe_return(20),
            "60d": _safe_return(60),
        },
        "price_vs_moving_averages": {
            "close_vs_sma_20": None if sma_20 in (None, 0) else round(close / sma_20 - 1, 6),
            "close_vs_sma_50": None if sma_50 in (None, 0) else round(close / sma_50 - 1, 6),
            "close_vs_ema_10": None if ema_10 in (None, 0) else round(close / ema_10 - 1, 6),
            "sma_20_vs_sma_50": None if sma_20 in (None, 0) or sma_50 in (None, 0) else round(sma_20 / sma_50 - 1, 6),
        },
        "momentum_context": {
            "macd": None if pd.isna(latest.get("macd")) else round(float(latest.get("macd")), 6),
            "macd_signal": None if pd.isna(latest.get("macds")) else round(float(latest.get("macds")), 6),
            "macd_hist": None if pd.isna(latest.get("macdh")) else round(float(latest.get("macdh")), 6),
            "macd_hist_change": None
            if len(df) < 2 or pd.isna(previous.get("macdh")) or pd.isna(latest.get("macdh"))
            else round(float(latest.get("macdh")) - float(previous.get("macdh")), 6),
            "rsi_14": None if pd.isna(latest.get("rsi")) else round(float(latest.get("rsi")), 6),
            "mfi_14": None if pd.isna(latest.get("mfi")) else round(float(latest.get("mfi")), 6),
        },
        "volatility_context": {
            "atr_14": None if atr_14 is None else round(atr_14, 6),
            "atr_pct_of_close": None if atr_14 in (None, 0) else round(atr_14 / close, 6),
            "boll_mid": None if pd.isna(latest.get("boll")) else round(float(latest.get("boll")), 6),
            "boll_upper": None if pd.isna(boll_upper) else round(float(boll_upper), 6),
            "boll_lower": None if pd.isna(boll_lower) else round(float(boll_lower), 6),
            "boll_position": boll_position,
        },
        "volume_context": {
            "volume": None if volume is None else round(volume, 4),
            "volume_ma_20": None if volume_ma_20 is None else round(volume_ma_20, 4),
            "volume_vs_ma_20": None if volume in (None,) or volume_ma_20 in (None, 0) else round(volume / volume_ma_20 - 1, 6),
            "volume_ratio": None if pd.isna(latest.get("volume_ratio")) else round(float(latest.get("volume_ratio")), 6),
            "turnover_rate": None if pd.isna(latest.get("turnover_rate")) else round(float(latest.get("turnover_rate")), 6),
            "vwma_20": None if pd.isna(latest.get("vwma")) else round(float(latest.get("vwma")), 6),
            "close_vs_vwma_20": None if pd.isna(latest.get("vwma")) or float(latest.get("vwma")) == 0 else round(close / float(latest.get("vwma")) - 1, 6),
            "net_mf_amount": None if pd.isna(latest.get("net_mf_amount")) else round(float(latest.get("net_mf_amount")), 4),
        },
    }


def _serialize_bars(df: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for _, row in df.iterrows():
        records.append(
            {
                "trade_date": row["trade_date"].strftime("%Y-%m-%d"),
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
                "pre_close": round(float(row["pre_close"]), 4),
                "volume": None if pd.isna(row["vol"]) else round(float(row["vol"]), 4),
                "amount": None if pd.isna(row["amount"]) else round(float(row["amount"]), 4),
            }
        )
    return records


def build_technical_data_bundle(
    ticker: str,
    analysis_date: str,
    lookback_trading_days: int = DEFAULT_LOOKBACK_TRADING_DAYS,
    benchmark_code: str = DEFAULT_BENCHMARK,
) -> dict[str, Any]:
    ts_code = _normalize_symbol(ticker)
    normalized = normalize_trade_date(analysis_date)
    effective_date = normalized["effective_trade_date"]
    effective_dt = datetime.strptime(effective_date, "%Y-%m-%d")
    start_dt = effective_dt - timedelta(days=max(lookback_trading_days * 2, 180))

    daily_bundle = _query_daily_bundle(ts_code, start_dt.strftime("%Y%m%d"), effective_dt.strftime("%Y%m%d"))
    if daily_bundle.empty:
        raise RuntimeError(f"No market data found for {ts_code} up to {effective_date}")

    daily_bundle = daily_bundle[daily_bundle["trade_date"] <= effective_dt].tail(lookback_trading_days).reset_index(drop=True)
    enriched = _compute_indicators(daily_bundle)
    benchmark = _fetch_benchmark_series(benchmark_code, start_dt.strftime("%Y%m%d"), effective_dt.strftime("%Y%m%d"))
    benchmark = benchmark[benchmark["trade_date"] <= effective_dt].tail(lookback_trading_days).reset_index(drop=True)
    meta = _fetch_security_meta(ts_code)
    latest = enriched.iloc[-1]

    return {
        "ticker": ts_code,
        "requested_date": normalized["requested_date"],
        "effective_trade_date": effective_date,
        "meta": {
            "name": meta.get("name"),
            "industry": meta.get("industry"),
            "market": meta.get("market"),
            "benchmark": benchmark_code,
            "sector_index": None,
        },
        "price_series": {
            "frequency": "1d",
            "adjustment": "qfq",
            "window_days": lookback_trading_days,
            "bars": _serialize_bars(enriched),
        },
        "market_snapshot": {
            "open": round(float(latest["open"]), 4),
            "high": round(float(latest["high"]), 4),
            "low": round(float(latest["low"]), 4),
            "close": round(float(latest["close"]), 4),
            "pre_close": round(float(latest["pre_close"]), 4),
            "volume": None if pd.isna(latest["vol"]) else round(float(latest["vol"]), 4),
            "amount": None if pd.isna(latest["amount"]) else round(float(latest["amount"]), 4),
            "turnover_rate": None if pd.isna(latest.get("turnover_rate")) else round(float(latest["turnover_rate"]), 4),
            "volume_ratio": None if pd.isna(latest.get("volume_ratio")) else round(float(latest["volume_ratio"]), 4),
            "up_limit": None if pd.isna(latest.get("up_limit")) else round(float(latest["up_limit"]), 4),
            "down_limit": None if pd.isna(latest.get("down_limit")) else round(float(latest["down_limit"]), 4),
            "net_mf_amount": None if pd.isna(latest.get("net_mf_amount")) else round(float(latest["net_mf_amount"]), 4),
        },
        "indicators": _latest_indicator_snapshot(enriched),
        "indicator_context": _build_indicator_context(enriched),
        "price_structure": _rolling_levels(enriched),
        "relative_strength": {
            **_compute_relative_strength(enriched, benchmark),
            "vs_sector_20d": None,
            "vs_sector_60d": None,
        },
        "data_quality": {
            "is_trade_date_aligned": normalized["is_trade_date_aligned"],
            "missing_fields": [],
            "source": "tushare",
            "adjustment": "qfq",
        },
    }


def get_extended_price_window(
    ticker: str,
    analysis_date: str,
    lookback_trading_days: int = 180,
) -> dict[str, Any]:
    return build_technical_data_bundle(
        ticker=ticker,
        analysis_date=analysis_date,
        lookback_trading_days=lookback_trading_days,
    )


def get_price_structure_levels(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_technical_data_bundle(ticker=ticker, analysis_date=analysis_date, lookback_trading_days=90)
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "price_structure": bundle["price_structure"],
    }


def get_moneyflow_context(ticker: str, analysis_date: str) -> dict[str, Any]:
    bundle = build_technical_data_bundle(ticker=ticker, analysis_date=analysis_date, lookback_trading_days=30)
    snapshot = bundle["market_snapshot"]
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "moneyflow": {
            "net_mf_amount": snapshot.get("net_mf_amount"),
            "turnover_rate": snapshot.get("turnover_rate"),
            "volume_ratio": snapshot.get("volume_ratio"),
        },
    }


def get_benchmark_relative_strength(
    ticker: str,
    analysis_date: str,
    benchmark_code: str = DEFAULT_BENCHMARK,
) -> dict[str, Any]:
    bundle = build_technical_data_bundle(
        ticker=ticker,
        analysis_date=analysis_date,
        lookback_trading_days=90,
        benchmark_code=benchmark_code,
    )
    return {
        "ticker": bundle["ticker"],
        "effective_trade_date": bundle["effective_trade_date"],
        "benchmark": benchmark_code,
        "relative_strength": {
            "vs_benchmark_20d": bundle["relative_strength"].get("vs_benchmark_20d"),
            "vs_benchmark_60d": bundle["relative_strength"].get("vs_benchmark_60d"),
        },
    }
