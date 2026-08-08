"""Orchestrates one full scan cycle:

1. Pull price data for the crypto + stock watchlists and score each with
   technical indicators.
2. Pull recent news headlines per symbol and score sentiment.
3. Combine into a confidence score. Anything >= MIN_CONFIDENCE is a
   candidate signal.
4. Re-fetch fresh data for candidates only and recompute ("double-check")
   before it's allowed to trigger a Telegram alert.
5. Respect a per-symbol cooldown so the same signal doesn't spam Telegram
   every 15 minutes.
6. Write public/data/latest.json (consumed by the Next.js dashboard) and
   data/state.json (alert cooldown memory).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import json

from lib import crypto_source, stock_source, indicators, news_source, scoring, state_store, telegram_notify
from lib.universe import (
    STOCK_UNIVERSE, STOCK_NAMES, CRYPTO_UNIVERSE, CRYPTO_NAMES, CRYPTO_BINANCE_SYMBOL,
)

MIN_CONFIDENCE = 70
VERIFY_DELAY_SECONDS = int(os.environ.get("VERIFY_DELAY_SECONDS", "45"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(ROOT, "public", "data", "latest.json")
STATE_PATH = os.path.join(ROOT, "data", "state.json")


def analyze_crypto(coin_id: str) -> dict | None:
    binance_symbol = CRYPTO_BINANCE_SYMBOL[coin_id]
    name = CRYPTO_NAMES.get(coin_id, coin_id)
    try:
        df = crypto_source.get_klines(binance_symbol, interval="1h", limit=150)
        price = float(df["close"].iloc[-1])
    except Exception as exc:
        print(f"[crypto] {coin_id} price fetch failed: {exc}")
        return None

    tech_score, tech_reasons = indicators.compute_technical_score(df)
    news_score, news_reasons, article_count = news_source.compute_news_score(f"{name} crypto")
    direction, confidence = scoring.combine_scores(tech_score, news_score)

    return {
        "symbol": binance_symbol,
        "raw_key": coin_id,
        "display_name": name,
        "market": "crypto",
        "direction": direction,
        "confidence": confidence,
        "technical_score": tech_score,
        "news_score": news_score,
        "price": price,
        "reasons": tech_reasons + news_reasons,
        "article_count": article_count,
    }


def analyze_stock(symbol: str) -> dict | None:
    name = STOCK_NAMES.get(symbol, symbol)
    try:
        df = stock_source.get_intraday(symbol)
        if df.empty:
            print(f"[stock] {symbol} no price data")
            return None
        price = stock_source.get_last_price(symbol, df)
    except Exception as exc:
        print(f"[stock] {symbol} price fetch failed: {exc}")
        return None

    tech_score, tech_reasons = indicators.compute_technical_score(df)
    news_score, news_reasons, article_count = news_source.compute_news_score(f"{name} stock")
    direction, confidence = scoring.combine_scores(tech_score, news_score)

    return {
        "symbol": symbol,
        "raw_key": symbol,
        "display_name": name,
        "market": "stock",
        "direction": direction,
        "confidence": confidence,
        "technical_score": tech_score,
        "news_score": news_score,
        "price": price,
        "reasons": tech_reasons + news_reasons,
        "article_count": article_count,
    }


def reverify(result: dict) -> dict | None:
    """Re-fetch fresh data for a single candidate and recompute its score."""
    time.sleep(VERIFY_DELAY_SECONDS)
    if result["market"] == "crypto":
        return analyze_crypto(result["raw_key"])
    return analyze_stock(result["raw_key"])


def main() -> None:
    state = state_store.load_state(STATE_PATH)
    results: list[dict] = []

    print(f"Scanning {len(CRYPTO_UNIVERSE)} crypto assets...")
    for coin_id in CRYPTO_UNIVERSE:
        r = analyze_crypto(coin_id)
        if r:
            results.append(r)
        time.sleep(0.5)

    print(f"Scanning {len(STOCK_UNIVERSE)} stocks...")
    for symbol in STOCK_UNIVERSE:
        r = analyze_stock(symbol)
        if r:
            results.append(r)
        time.sleep(0.5)

    candidates = [r for r in results if r["confidence"] >= MIN_CONFIDENCE]
    print(f"{len(candidates)} candidate(s) crossed {MIN_CONFIDENCE}% on first pass, re-verifying...")

    alerts_sent = 0
    for candidate in candidates:
        verified = reverify(candidate)
        key = f"{candidate['market']}:{candidate['raw_key']}"

        if not verified or verified["confidence"] < MIN_CONFIDENCE or verified["direction"] != candidate["direction"]:
            print(f"[verify] {candidate['symbol']} did not hold up on re-check, not alerting")
            for r in results:
                if r["raw_key"] == candidate["raw_key"] and r["market"] == candidate["market"]:
                    r["verified"] = False
            continue

        # Use the re-verified numbers (more recent) in the published dataset.
        for i, r in enumerate(results):
            if r["raw_key"] == candidate["raw_key"] and r["market"] == candidate["market"]:
                verified["verified"] = True
                results[i] = verified
                break

        if state_store.should_alert(state, key, verified["direction"], verified["confidence"]):
            message = telegram_notify.format_signal_message(verified)
            if DRY_RUN:
                print("[dry-run] would send Telegram message:\n" + message)
                sent = True
            else:
                sent = telegram_notify.send_telegram_message(message)
            if sent:
                state_store.record_alert(state, key, verified["direction"], verified["confidence"])
                alerts_sent += 1
        else:
            print(f"[cooldown] {verified['symbol']} still within cooldown, skipping alert")

    for r in results:
        r.setdefault("verified", False)
        r["last_alert_at"] = state.get(f"{r['market']}:{r['raw_key']}", {}).get("last_alert_at")
        r.pop("raw_key", None)
        r.pop("article_count", None)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "Automated technical + news-sentiment signals. Not financial advice. Educational use only.",
        "min_confidence_threshold": MIN_CONFIDENCE,
        "watchlist_counts": {"crypto": len(CRYPTO_UNIVERSE), "stock": len(STOCK_UNIVERSE)},
        "signals": results,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    state_store.save_state(STATE_PATH, state)
    print(f"Done. {len(results)} symbols scanned, {alerts_sent} Telegram alert(s) sent.")


if __name__ == "__main__":
    main()
