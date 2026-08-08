"""Stock price data via Yahoo Finance's public chart API (no key required).

Calls the chart endpoint directly with a browser User-Agent instead of going
through the yfinance library, which has proven unreliable (empty/blocked
responses) in some sandboxed network environments.
"""
from __future__ import annotations

import pandas as pd
import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _fetch_chart(symbol: str, range_: str, interval: str) -> dict:
    resp = requests.get(
        CHART_URL.format(symbol=symbol),
        params={"range": range_, "interval": interval},
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"no chart data for {symbol}: {data.get('chart', {}).get('error')}")
    return result[0]


def _to_dataframe(result: dict) -> pd.DataFrame:
    timestamps = result.get("timestamp")
    if not timestamps:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    quote = result["indicators"]["quote"][0]
    df = pd.DataFrame({
        "open": quote["open"],
        "high": quote["high"],
        "low": quote["low"],
        "close": quote["close"],
        "volume": quote["volume"],
    }, index=pd.to_datetime(timestamps, unit="s"))
    return df.dropna()


def get_intraday(symbol: str, range_: str = "5d", interval: str = "15m") -> pd.DataFrame:
    try:
        result = _fetch_chart(symbol, range_, interval)
        df = _to_dataframe(result)
    except Exception:
        df = pd.DataFrame()

    if df.empty:
        # Market may be closed with no recent intraday bars; fall back to daily.
        result = _fetch_chart(symbol, "3mo", "1d")
        df = _to_dataframe(result)
    return df


def get_last_price(symbol: str, df: pd.DataFrame | None = None) -> float:
    if df is not None and not df.empty:
        return float(df["close"].iloc[-1])
    result = _fetch_chart(symbol, "1d", "1m")
    meta = result.get("meta", {})
    return float(meta["regularMarketPrice"])
