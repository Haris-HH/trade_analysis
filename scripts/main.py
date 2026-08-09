"""Orchestrates one full scan cycle across ~1000 symbols (all Bitkub-listed
crypto + S&P 500 + liquid Thai SET stocks):

1. Fetch price data for every symbol IN PARALLEL and score it with technical
   indicators only (cheap: one HTTP request per symbol, no news lookup yet).
2. News sentiment can only ever contribute NEWS_WEIGHT*100 points to the
   combined score (see scoring.py), so a symbol whose technical score alone
   can't mathematically reach MIN_CONFIDENCE even with maximal same-direction
   news is skipped — this keeps the slow, rate-limit-sensitive news lookups
   (Google News RSS) down to a handful of symbols per run instead of ~1000.
3. For the surviving candidates, fetch news and compute the combined
   confidence score. Anything >= MIN_CONFIDENCE is an alert candidate.
4. Wait once (VERIFY_DELAY_SECONDS), then re-fetch + recompute all
   candidates in parallel ("double-check") before allowing a Telegram alert.
5. Respect a per-symbol cooldown so the same signal doesn't spam Telegram
   every scan cycle.
6. Write public/data/latest.json (consumed by the Next.js dashboard) and
   data/state.json (alert cooldown memory).
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import json

from lib import bitkub_source, stock_source, indicators, news_source, scoring, state_store, telegram_notify, chart
from lib.universe import STOCK_NAMES
from lib.scoring import NEWS_WEIGHT

MIN_CONFIDENCE = 70
VERIFY_DELAY_SECONDS = int(os.environ.get("VERIFY_DELAY_SECONDS", "45"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"
PRICE_FETCH_WORKERS = int(os.environ.get("PRICE_FETCH_WORKERS", "16"))

# A symbol whose technical score is below this can never reach MIN_CONFIDENCE
# even with perfect (100, same-direction) news sentiment, given the fixed
# TECH_WEIGHT/NEWS_WEIGHT split in scoring.py. A few points of margin are
# kept below the exact cutoff to be safe against rounding.
_exact_cutoff = (MIN_CONFIDENCE - NEWS_WEIGHT * 100) / (1 - NEWS_WEIGHT)
TECH_PREFILTER_THRESHOLD = max(0.0, _exact_cutoff - 5)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(ROOT, "public", "data", "latest.json")
STATE_PATH = os.path.join(ROOT, "data", "state.json")


def build_universe() -> list[dict]:
    items = []
    crypto_universe = bitkub_source.get_universe()
    for ticker, name in crypto_universe.items():
        items.append({"market": "crypto", "ticker": ticker, "name": name})
    for ticker, name in STOCK_NAMES.items():
        items.append({"market": "stock", "ticker": ticker, "name": name})
    return items


def fetch_price_data(item: dict) -> tuple[dict, object] | None:
    """Returns (item, price_df) or None on failure."""
    try:
        if item["market"] == "crypto":
            df = bitkub_source.get_klines(item["ticker"])
        else:
            df = stock_source.get_intraday(item["ticker"])
        if df is None or df.empty:
            return None
        return item, df
    except Exception as exc:
        print(f"[price] {item['market']}:{item['ticker']} failed: {exc}")
        return None


def technical_pass(item: dict, df) -> dict:
    tech_score, tech_reasons = indicators.compute_technical_score(df)
    if item["market"] == "crypto":
        price = bitkub_source.get_last_price(item["ticker"], df)
        display_symbol = f"{item['ticker']}/THB"
    else:
        price = stock_source.get_last_price(item["ticker"], df)
        display_symbol = item["ticker"]

    return {
        "market": item["market"],
        "raw_key": item["ticker"],
        "symbol": display_symbol,
        "display_name": item["name"],
        "technical_score": tech_score,
        "tech_reasons": tech_reasons,
        "price": price,
        "sparkline": chart.extract_sparkline(df),
    }


def add_news_and_score(partial: dict) -> dict:
    query = f"{partial['display_name']} {'crypto' if partial['market'] == 'crypto' else 'stock'}"
    news_ticker = partial["raw_key"] if partial["market"] == "stock" else None
    news_score, news_reasons, _ = news_source.compute_news_score(query, ticker=news_ticker)
    direction, confidence = scoring.combine_scores(partial["technical_score"], news_score)

    return {
        **partial,
        "direction": direction,
        "confidence": confidence,
        "news_score": news_score,
        "reasons": partial["tech_reasons"] + news_reasons,
    }


def scan_universe(universe: list[dict]) -> list[dict]:
    technical_results = []
    with ThreadPoolExecutor(max_workers=PRICE_FETCH_WORKERS) as pool:
        futures = [pool.submit(fetch_price_data, item) for item in universe]
        for future in as_completed(futures):
            result = future.result()
            if result is None:
                continue
            item, df = result
            try:
                technical_results.append(technical_pass(item, df))
            except Exception as exc:
                print(f"[technical] {item['market']}:{item['ticker']} failed: {exc}")

    print(f"Priced {len(technical_results)}/{len(universe)} symbols.")

    needs_news, skipped = [], []
    for r in technical_results:
        (needs_news if abs(r["technical_score"]) >= TECH_PREFILTER_THRESHOLD else skipped).append(r)
    print(f"{len(needs_news)} symbol(s) cleared the technical prefilter (>= {TECH_PREFILTER_THRESHOLD:.0f}), fetching news for those...")

    scored = []
    for partial in needs_news:
        scored.append(add_news_and_score(partial))
        time.sleep(0.3)

    # Symbols that never got a news lookup still get a neutral (0) news score
    # so the dashboard can show the full universe, not just the candidates.
    for partial in skipped:
        direction, confidence = scoring.combine_scores(partial["technical_score"], 0.0)
        scored.append({**partial, "direction": direction, "confidence": confidence, "news_score": 0.0, "reasons": partial["tech_reasons"]})

    return scored


def reverify_candidates(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    print(f"Waiting {VERIFY_DELAY_SECONDS}s before re-verifying {len(candidates)} candidate(s)...")
    time.sleep(VERIFY_DELAY_SECONDS)

    def _reverify(candidate: dict) -> dict | None:
        item = {"market": candidate["market"], "ticker": candidate["raw_key"], "name": candidate["display_name"]}
        result = fetch_price_data(item)
        if result is None:
            return None
        _, df = result
        partial = technical_pass(item, df)
        return add_news_and_score(partial)

    verified = []
    with ThreadPoolExecutor(max_workers=min(PRICE_FETCH_WORKERS, len(candidates))) as pool:
        futures = {pool.submit(_reverify, c): c for c in candidates}
        for future in as_completed(futures):
            original = futures[future]
            result = future.result()
            if result is None:
                print(f"[verify] {original['symbol']} re-fetch failed, not alerting")
                continue
            verified.append((original, result))
    return verified


def main() -> None:
    state = state_store.load_state(STATE_PATH)
    universe = build_universe()
    print(f"Universe: {sum(1 for u in universe if u['market'] == 'crypto')} crypto, "
          f"{sum(1 for u in universe if u['market'] == 'stock')} stocks.")

    results = scan_universe(universe)

    by_key = {(r["market"], r["raw_key"]): i for i, r in enumerate(results)}
    candidates = [r for r in results if r["confidence"] >= MIN_CONFIDENCE]
    print(f"{len(candidates)} candidate(s) crossed {MIN_CONFIDENCE}% on first pass.")

    alerts_sent = 0
    for original, verified in reverify_candidates(candidates):
        key = f"{verified['market']}:{verified['raw_key']}"

        if verified["confidence"] < MIN_CONFIDENCE or verified["direction"] != original["direction"]:
            print(f"[verify] {verified['symbol']} did not hold up on re-check, not alerting")
            continue

        idx = by_key.get((verified["market"], verified["raw_key"]))
        if idx is not None:
            verified["verified"] = True
            results[idx] = verified

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
        r.pop("tech_reasons", None)

    crypto_count = sum(1 for u in universe if u["market"] == "crypto")
    stock_count = sum(1 for u in universe if u["market"] == "stock")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "Automated technical + news-sentiment signals. Not financial advice. Educational use only.",
        "min_confidence_threshold": MIN_CONFIDENCE,
        "watchlist_counts": {"crypto": crypto_count, "stock": stock_count},
        "signals": results,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    state_store.save_state(STATE_PATH, state)
    print(f"Done. {len(results)} symbols scanned, {alerts_sent} Telegram alert(s) sent.")


if __name__ == "__main__":
    main()
