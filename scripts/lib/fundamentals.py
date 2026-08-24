"""Lightweight fundamental read for crypto, sourced from CoinGecko's free
/coins/markets endpoint: market-cap rank (the closest computable proxy for
"มีโปรเจกต์และทีมงานเบื้องหลังที่น่าเชื่อถือหรือไม่" — genuine team/project
credibility can't be automated, but a large, long-lived market cap is the
closest available signal) and circulating/total supply ratio (a large gap
means heavy future dilution overhang from token unlocks — directly the
checklist's "ดูปริมาณเหรียญทั้งหมด (Total Supply) และเหรียญที่หมุนเวียนใน
ระบบ (Circulating Supply)").

Fetched once and cached to disk (data/coingecko_cache.json, committed back
to the repo by the CI workflow the same way data/state.json is, since
GitHub Actions runners are ephemeral and would otherwise lose the cache
every run) with a 12h TTL — supply/rank data barely moves intraday, and
this avoids re-fetching ~1000 coins' worth of data every 5-minute scan
cycle for what is otherwise near-static data.
"""
from __future__ import annotations

import json
import os
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_PATH = os.path.join(ROOT, "data", "coingecko_cache.json")
CACHE_TTL_SECONDS = 12 * 3600
PAGES = 4  # 4 * 250 = top 1000 coins by market cap, comfortably covers every Bitkub-listed ticker
TIMEOUT = 15


def _fetch_from_coingecko() -> dict:
    by_symbol: dict[str, dict] = {}
    for page in range(1, PAGES + 1):
        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd", "order": "market_cap_desc",
                    "per_page": 250, "page": page, "sparkline": "false",
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            rows = resp.json()
        except Exception as exc:
            print(f"[fundamentals] CoinGecko page {page} fetch failed: {exc}")
            break
        if not rows:
            break
        for row in rows:
            symbol = (row.get("symbol") or "").upper()
            # Keep the first (highest market-cap) match for a duplicate
            # ticker — the dominant coin for a symbol is the right project
            # to use as a proxy almost always, and results already arrive
            # sorted by market_cap_desc.
            if symbol and symbol not in by_symbol:
                circulating, total = row.get("circulating_supply"), row.get("total_supply")
                by_symbol[symbol] = {
                    "market_cap_rank": row.get("market_cap_rank"),
                    "circulating_supply": circulating,
                    "total_supply": total,
                    "supply_ratio": (circulating / total) if circulating and total and total > 0 else None,
                }
    return by_symbol


def get_fundamentals_map() -> dict:
    """Returns {SYMBOL: {market_cap_rank, circulating_supply, total_supply,
    supply_ratio}}, refreshing the on-disk cache if it's stale or missing.
    Falls back to a stale cache (rather than an empty map) if a refresh
    fails, and to an empty map if there's no cache at all — either way, a
    missing entry means "no fundamental opinion" for that symbol, not a
    weak vote (same ABSTAIN-style pattern as every other optional factor)."""
    cached = None
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
        except (OSError, json.JSONDecodeError):
            cached = None

    if cached and time.time() - cached.get("fetched_at", 0) < CACHE_TTL_SECONDS:
        return cached["by_symbol"]

    fresh = _fetch_from_coingecko()
    if fresh:
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": time.time(), "by_symbol": fresh}, f)
        except OSError as exc:
            print(f"[fundamentals] could not write cache: {exc}")
        return fresh

    if cached:
        print("[fundamentals] refresh failed, using stale cache")
        return cached["by_symbol"]

    print("[fundamentals] no data available (fetch failed, no cache) — fundamental factor omitted this run")
    return {}
