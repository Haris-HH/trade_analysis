"""Crypto universe + price data sourced directly from Bitkub's public API.

Using Bitkub itself (rather than Binance) means the watchlist can cover every
coin actually listed on Bitkub, and the price data reflects the market this
project's users actually trade on (THB-quoted), not a foreign-exchange proxy.
No API key is required for these public endpoints.
"""
from __future__ import annotations

import pandas as pd
import requests

BASE_URL = "https://api.bitkub.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Fiat-pegged stablecoins never produce a meaningful BUY/SELL signal (price
# barely moves), so scanning them just wastes API budget.
STABLECOIN_EXCLUDE = {
    "USDT", "USDC", "USDS", "RLUSD", "USD1", "FRAX", "BUSD", "TUSD", "USDP",
    "DAI", "GUSD", "EUROC", "PYUSD",
}


# Populated by get_universe() as a side effect (that endpoint already fetches
# every field we need — no reason to hit it twice) and read by
# is_broker_sourced() for the auto-trader. "broker"-sourced coins are listed
# and priceable like any other market, but /api/v3/market/place-bid|place-ask
# reject them outright (error 61: "This endpoint doesn't support broker
# coins" — confirmed 2026-08-21 against a live order attempt), so the
# auto-trader must not try to buy them.
_source_cache: dict[str, str] = {}


def get_universe() -> dict[str, str]:
    """Returns {ticker: display_name} for every active, non-stablecoin THB market
    on Bitkub. Uses the v3 symbols endpoint — the unversioned /api/market/symbols
    endpoint now hangs indefinitely instead of responding (observed 2026-08-14)."""
    resp = requests.get(f"{BASE_URL}/api/v3/market/symbols", headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    universe: dict[str, str] = {}
    for row in data.get("result", []):
        if row.get("quote_asset") != "THB" or row.get("status") != "active":
            continue
        ticker = row.get("base_asset", "")
        if not ticker or ticker in STABLECOIN_EXCLUDE:
            continue
        description = row.get("description", "")
        name = description[len("Thai Baht to "):] if description.startswith("Thai Baht to ") else ticker
        universe[ticker] = name
        _source_cache[ticker] = row.get("source", "exchange")
    return universe


def is_broker_sourced(ticker: str) -> bool:
    return _source_cache.get(ticker) == "broker"


def get_klines(ticker: str, resolution: str = "60", bars: int = 150) -> pd.DataFrame:
    """Hourly OHLCV candles for `{ticker}_THB` via Bitkub's TradingView-compatible endpoint."""
    import time as _time

    to_ts = int(_time.time())
    from_ts = to_ts - bars * int(resolution) * 60

    resp = requests.get(
        f"{BASE_URL}/tradingview/history",
        params={"symbol": f"{ticker}_THB", "resolution": resolution, "from": from_ts, "to": to_ts},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("s") != "ok" or not data.get("c"):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame({
        "open": data["o"], "high": data["h"], "low": data["l"],
        "close": data["c"], "volume": data["v"],
    }, index=pd.to_datetime(data["t"], unit="s"))
    return df


def get_last_price(ticker: str, df: pd.DataFrame | None = None) -> float:
    if df is not None and not df.empty:
        return float(df["close"].iloc[-1])
    resp = requests.get(f"{BASE_URL}/api/market/ticker", params={"sym": f"THB_{ticker}"}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return float(data[f"THB_{ticker}"]["last"])
