from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Callable

import pandas as pd

try:
    import tushare as ts
except ImportError:  # pragma: no cover - handled at runtime for optional dependency
    ts = None

from .config import get_config


SUPPORTED_INDICATORS = {
    "close_50_sma": "50 SMA: A medium-term trend indicator.",
    "close_200_sma": "200 SMA: A long-term trend benchmark.",
    "close_10_ema": "10 EMA: A responsive short-term average.",
    "macd": "MACD: Trend-following momentum indicator.",
    "macds": "MACD Signal: Smoothed MACD line.",
    "macdh": "MACD Histogram: MACD minus signal line.",
    "rsi": "RSI: Momentum oscillator for overbought/oversold conditions.",
    "boll": "Bollinger Middle: 20-day moving average.",
    "boll_ub": "Bollinger Upper Band: 20-day average plus two standard deviations.",
    "boll_lb": "Bollinger Lower Band: 20-day average minus two standard deviations.",
    "atr": "ATR: Average true range for volatility.",
    "vwma": "VWMA: Volume weighted moving average.",
    "mfi": "MFI: Money flow index using price and volume.",
}


def _require_tushare():
    if ts is None:
        raise RuntimeError(
            "tushare is not installed. Install dependency 'tushare' before using the tushare vendor."
        )

    token = _get_tushare_token()
    if not token:
        raise RuntimeError(
            "Missing Tushare token. Set config/tushare.toml or config['tushare_token']."
        )

    # Avoid global token file writes so multiple graph branches can call Tushare in parallel safely.
    return ts.pro_api(token=token)


def _get_tushare_token() -> str | None:
    config = get_config()
    return (
        config.get("tushare_token")
        or _load_project_tushare_token()
        or os.getenv("TUSHARE_TOKEN")
        or os.getenv("TUSHARE_API_TOKEN")
    )


def _load_project_tushare_token() -> str | None:
    project_dir = Path(get_config().get("project_dir", Path.cwd()))
    config_path = project_dir.parent / "config" / "tushare.toml"
    if not config_path.exists():
        return None

    content = config_path.read_text(encoding="utf-8")
    match = re.search(r'^\s*token\s*=\s*["\']([^"\']+)["\']\s*$', content, flags=re.MULTILINE)
    if not match:
        return None

    token = match.group(1).strip()
    return token or None


def _normalize_symbol(symbol: str) -> str:
    raw_text = symbol.strip()
    raw = raw_text.upper()
    if "." in raw:
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 6:
        pro = _require_tushare()
        basic = _read_or_query(
            "stock_basic_active_lookup",
            {"list_status": "L"},
            lambda: pro.stock_basic(list_status="L", fields="ts_code,symbol,name"),
        )
        if not basic.empty:
            matches = basic[basic["name"].astype(str).str.strip() == raw_text]
            if matches.empty:
                matches = basic[basic["symbol"].astype(str).str.upper() == raw]
            if not matches.empty:
                ts_code = str(matches.iloc[0].get("ts_code") or "").strip().upper()
                if ts_code:
                    return ts_code
        raise ValueError(
            f"Unsupported A-share symbol '{symbol}'. Expected ts_code like 600519.SH or 000001.SZ."
        )

    if digits.startswith(("600", "601", "603", "605", "688", "689", "510", "511", "512", "513", "515", "518")):
        return f"{digits}.SH"
    return f"{digits}.SZ"


def _cache_dir() -> str:
    config = get_config()
    base_dir = config.get("data_cache_dir", "data_cache")
    path = os.path.join(base_dir, "tushare")
    os.makedirs(path, exist_ok=True)
    return path


def _cache_key(endpoint: str, params: dict) -> str:
    payload = json.dumps(params, sort_keys=True, ensure_ascii=True)
    digest = hashlib.md5(payload.encode("utf-8")).hexdigest()
    return os.path.join(_cache_dir(), f"{endpoint}_{digest}.csv")


def _read_or_query(endpoint: str, params: dict, query_func: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    cache_file = _cache_key(endpoint, params)
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file)

    df = query_func()
    if isinstance(df, pd.DataFrame):
        df.to_csv(cache_file, index=False)
        return df

    raise RuntimeError(f"Unexpected response type for endpoint '{endpoint}'")


def _query_daily_bundle(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    pro = _require_tushare()
    params = {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}

    daily = _read_or_query(
        "daily",
        params,
        lambda: pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date),
    )
    adj_factor = _read_or_query(
        "adj_factor",
        params,
        lambda: pro.adj_factor(ts_code=ts_code, start_date=start_date, end_date=end_date),
    )
    daily_basic = _read_or_query(
        "daily_basic",
        params,
        lambda: pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date),
    )
    moneyflow = _read_or_query(
        "moneyflow",
        params,
        lambda: pro.moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date),
    )
    stk_limit = _read_or_query(
        "stk_limit",
        params,
        lambda: pro.stk_limit(ts_code=ts_code, start_date=start_date, end_date=end_date),
    )

    if daily.empty:
        return daily

    merged = daily.merge(adj_factor, on=["ts_code", "trade_date"], how="left")
    merged = merged.merge(daily_basic, on=["ts_code", "trade_date"], how="left", suffixes=("", "_daily_basic"))
    merged = merged.merge(stk_limit, on=["ts_code", "trade_date"], how="left")
    merged = merged.merge(moneyflow, on=["ts_code", "trade_date"], how="left", suffixes=("", "_moneyflow"))
    merged["trade_date"] = pd.to_datetime(merged["trade_date"], format="%Y%m%d")
    merged = merged.sort_values("trade_date").reset_index(drop=True)

    latest_adj = merged["adj_factor"].dropna().iloc[-1] if merged["adj_factor"].notna().any() else 1.0
    for price_col in ("open", "high", "low", "close", "pre_close"):
        merged[f"{price_col}_qfq"] = (merged[price_col] * merged["adj_factor"] / latest_adj).round(4)

    # Downstream agents should consume qfq prices by default.
    for price_col in ("open", "high", "low", "close", "pre_close"):
        merged[f"raw_{price_col}"] = merged[price_col]
        merged[price_col] = merged[f"{price_col}_qfq"]

    merged["vol"] = pd.to_numeric(merged.get("vol"), errors="coerce")
    merged["amount"] = pd.to_numeric(merged.get("amount"), errors="coerce")

    return merged


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    close = pd.to_numeric(result["close"], errors="coerce")
    high = pd.to_numeric(result["high"], errors="coerce")
    low = pd.to_numeric(result["low"], errors="coerce")
    volume = pd.to_numeric(result["vol"], errors="coerce")

    result["close_50_sma"] = close.rolling(50).mean()
    result["close_200_sma"] = close.rolling(200).mean()
    result["close_10_ema"] = close.ewm(span=10, adjust=False).mean()

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    result["macd"] = ema12 - ema26
    result["macds"] = result["macd"].ewm(span=9, adjust=False).mean()
    result["macdh"] = result["macd"] - result["macds"]

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    result["rsi"] = 100 - (100 / (1 + rs))

    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    result["atr"] = true_range.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()

    mid = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    result["boll"] = mid
    result["boll_ub"] = mid + 2 * std
    result["boll_lb"] = mid - 2 * std

    price_volume = close * volume
    result["vwma"] = price_volume.rolling(20).sum() / volume.rolling(20).sum()

    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    positive_flow = money_flow.where(typical_price > typical_price.shift(1), 0.0)
    negative_flow = money_flow.where(typical_price < typical_price.shift(1), 0.0)
    pos_sum = positive_flow.rolling(14).sum()
    neg_sum = negative_flow.rolling(14).sum()
    money_ratio = pos_sum / neg_sum.replace(0, pd.NA)
    result["mfi"] = 100 - (100 / (1 + money_ratio))

    return result


def get_tushare_stock_data(
    symbol: Annotated[str, "A-share ticker like 600519.SH or 000001.SZ"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
):
    ts_code = _normalize_symbol(symbol)
    start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
    end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")

    data = _query_daily_bundle(ts_code, start, end)
    if data.empty:
        return f"No data found for symbol '{ts_code}' between {start_date} and {end_date}"

    display = data[
        [
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "vol",
            "amount",
            "turnover_rate",
            "volume_ratio",
            "up_limit",
            "down_limit",
        ]
    ].copy()
    display = display.rename(
        columns={
            "trade_date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "pre_close": "Pre Close",
            "vol": "Volume",
            "amount": "Amount",
            "turnover_rate": "Turnover Rate",
            "volume_ratio": "Volume Ratio",
            "up_limit": "Up Limit",
            "down_limit": "Down Limit",
        }
    )
    display["Date"] = display["Date"].dt.strftime("%Y-%m-%d")

    header = f"# Tushare qfq stock data for {ts_code} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(display)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + display.to_csv(index=False)


def get_tushare_indicator(
    symbol: Annotated[str, "A-share ticker like 600519.SH or 000001.SZ"],
    indicator: Annotated[str, "technical indicator name"],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
) -> str:
    if indicator not in SUPPORTED_INDICATORS:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(SUPPORTED_INDICATORS.keys())}"
        )

    ts_code = _normalize_symbol(symbol)
    current_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = current_dt - timedelta(days=max(look_back_days * 4, 260))

    data = _query_daily_bundle(
        ts_code,
        start_dt.strftime("%Y%m%d"),
        current_dt.strftime("%Y%m%d"),
    )
    if data.empty:
        return f"No data found for symbol '{ts_code}' up to {curr_date}"

    enriched = _compute_indicators(data)
    window = enriched[enriched["trade_date"] <= current_dt].tail(look_back_days + 1)

    lines = []
    for _, row in window.sort_values("trade_date", ascending=False).iterrows():
        value = row.get(indicator)
        rendered = "N/A" if pd.isna(value) else str(round(float(value), 6))
        lines.append(f"{row['trade_date'].strftime('%Y-%m-%d')}: {rendered}")

    result_str = (
        f"## {indicator} values from {window['trade_date'].min().strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        + "\n".join(lines)
        + "\n\n"
        + SUPPORTED_INDICATORS[indicator]
    )
    return result_str


def _latest_record_before(df: pd.DataFrame, curr_date: str, date_columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df

    current_dt = pd.to_datetime(curr_date)
    working = df.copy()
    sort_col = None
    for col in date_columns:
        if col in working.columns:
            working[col] = pd.to_datetime(working[col], format="%Y%m%d", errors="coerce")
            if sort_col is None:
                sort_col = col
    if sort_col is None:
        return working.head(1)

    filtered = working[working[sort_col] <= current_dt]
    if filtered.empty:
        filtered = working
    return filtered.sort_values(sort_col, ascending=False).head(1)


def get_tushare_fundamentals(
    ticker: Annotated[str, "A-share ticker like 600519.SH or 000001.SZ"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
):
    ts_code = _normalize_symbol(ticker)
    curr_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    pro = _require_tushare()

    basic = _read_or_query(
        "stock_basic",
        {"ts_code": ts_code},
        lambda: pro.stock_basic(ts_code=ts_code),
    )
    daily_basic = _read_or_query(
        "daily_basic_latest",
        {"ts_code": ts_code, "end_date": curr_date},
        lambda: pro.daily_basic(ts_code=ts_code, start_date=(datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y%m%d"), end_date=datetime.strptime(curr_date, "%Y-%m-%d").strftime("%Y%m%d")),
    )
    fina_indicator = _read_or_query(
        "fina_indicator",
        {"ts_code": ts_code},
        lambda: pro.fina_indicator(ts_code=ts_code),
    )

    basic_row = basic.head(1).iloc[0] if not basic.empty else pd.Series(dtype=object)
    daily_row_df = _latest_record_before(daily_basic, curr_date, ["trade_date"])
    fina_row_df = _latest_record_before(fina_indicator, curr_date, ["end_date", "ann_date"])
    daily_row = daily_row_df.iloc[0] if not daily_row_df.empty else pd.Series(dtype=object)
    fina_row = fina_row_df.iloc[0] if not fina_row_df.empty else pd.Series(dtype=object)

    fields = [
        ("TS Code", ts_code),
        ("Name", basic_row.get("name")),
        ("Industry", basic_row.get("industry")),
        ("List Date", basic_row.get("list_date")),
        ("Market", basic_row.get("market")),
        ("Total Market Value", daily_row.get("total_mv")),
        ("Float Market Value", daily_row.get("circ_mv")),
        ("PE", daily_row.get("pe")),
        ("PB", daily_row.get("pb")),
        ("PS", daily_row.get("ps")),
        ("Dividend Yield", daily_row.get("dv_ratio")),
        ("Turnover Rate", daily_row.get("turnover_rate")),
        ("ROE", fina_row.get("roe")),
        ("ROA", fina_row.get("roa")),
        ("Gross Margin", fina_row.get("grossprofit_margin")),
        ("Net Profit Margin", fina_row.get("netprofit_margin")),
        ("Debt To Assets", fina_row.get("debt_to_assets")),
        ("Current Ratio", fina_row.get("current_ratio")),
        ("Quick Ratio", fina_row.get("quick_ratio")),
        ("Basic EPS", fina_row.get("eps")),
        ("BVPS", fina_row.get("bps")),
        ("Revenue YoY", fina_row.get("tr_yoy")),
        ("Net Profit YoY", fina_row.get("netprofit_yoy")),
    ]

    rendered = [f"## Fundamentals overview for {ts_code} as of {curr_date}\n"]
    for name, value in fields:
        if pd.notna(value):
            rendered.append(f"- {name}: {value}")

    if len(rendered) == 1:
        rendered.append("- No fundamentals data found")
    return "\n".join(rendered)


def _statement_to_markdown(
    endpoint: str,
    ticker: str,
    freq: str = "quarterly",
    curr_date: str = None,
):
    ts_code = _normalize_symbol(ticker)
    curr_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    pro = _require_tushare()

    endpoint_func = getattr(pro, endpoint)
    df = _read_or_query(endpoint, {"ts_code": ts_code}, lambda: endpoint_func(ts_code=ts_code))
    if df.empty:
        return f"No {endpoint} data found for symbol '{ts_code}'"

    working = df.copy()
    if "end_date" in working.columns:
        working["end_date"] = pd.to_datetime(working["end_date"], format="%Y%m%d", errors="coerce")
        working = working[working["end_date"] <= pd.to_datetime(curr_date)]
        working = working.sort_values("end_date", ascending=False)

    if freq == "annual":
        if "end_date" in working.columns:
            working = working[working["end_date"].dt.month == 12]
        limit = 4
    else:
        limit = 4

    display = working.head(limit).copy()
    for col in display.columns:
        if pd.api.types.is_datetime64_any_dtype(display[col]):
            display[col] = display[col].dt.strftime("%Y-%m-%d")

    return f"## {endpoint} data for {ts_code}\n\n" + display.to_csv(index=False)


def get_tushare_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    return _statement_to_markdown("balancesheet", ticker, freq, curr_date)


def get_tushare_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    return _statement_to_markdown("cashflow", ticker, freq, curr_date)


def get_tushare_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    return _statement_to_markdown("income", ticker, freq, curr_date)
