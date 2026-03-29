from __future__ import annotations

import json


TECHNICAL_OUTPUT_TEMPLATE = {
    "ticker": "",
    "effective_trade_date": "",
    "trend": {
        "short_term": "bullish | bearish | sideways",
        "medium_term": "bullish | bearish | sideways",
        "strength": 0.0,
        "summary": "",
        "evidence": [],
    },
    "momentum": {
        "state": "accelerating | weakening | neutral",
        "strength": 0.0,
        "summary": "",
        "evidence": [],
    },
    "volatility": {
        "state": "expanding | contracting | normal",
        "summary": "",
        "evidence": [],
    },
    "volume_confirmation": {
        "state": "confirming | diverging | neutral",
        "summary": "",
        "evidence": [],
    },
    "relative_strength": {
        "vs_benchmark": "stronger | weaker | neutral",
        "vs_sector": "stronger | weaker | neutral",
        "summary": "",
        "evidence": [],
    },
    "indicator_snapshot": {
        "price_vs_sma20": None,
        "price_vs_sma50": None,
        "price_vs_ema10": None,
        "sma20_vs_sma50": None,
        "macd": None,
        "macd_signal": None,
        "macd_hist": None,
        "macd_hist_change": None,
        "rsi_14": None,
        "mfi_14": None,
        "atr_14": None,
        "atr_pct_of_close": None,
        "boll_position": None,
        "volume_vs_ma20": None,
        "close_vs_vwma20": None,
        "rs_vs_benchmark_20d": None,
        "rs_vs_benchmark_60d": None,
    },
    "key_levels": {
        "support": [],
        "resistance": [],
        "breakout_level": None,
        "breakdown_level": None,
    },
    "signals": [
        {
            "type": "trend_following | breakout | mean_reversion | divergence",
            "direction": "bullish | bearish | neutral",
            "strength": 0.0,
            "description": "",
            "evidence": [],
        }
    ],
    "risk_flags": [],
    "invalidations": [],
    "confidence": 0.0,
    "technical_summary_zh": "",
}


def get_output_template_json() -> str:
    return json.dumps(TECHNICAL_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)
