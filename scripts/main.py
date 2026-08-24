"""Orchestrates one full scan cycle across ~1000 symbols (all Bitkub-listed
crypto + S&P 500 + liquid Thai SET stocks), using a regime-aware confluence
engine ported from QuantDesk (D:\\Haris\\Quantdesk\\core\\signals.py):

1. Fetch price data for every symbol IN PARALLEL and score it with technical
   factors only (cheap: one HTTP request per symbol, no news lookup yet).
   Below MIN_CANDLES the engine returns no factors at all — "no opinion"
   (ABSTAIN), not a weak guess.
2. News can only ever contribute WEIGHTS["news"] of the total weight, so a
   symbol whose technical factors alone can't mathematically reach
   MIN_CONFIDENCE even with maximal same-direction news is skipped — this
   keeps news lookups down to a handful of symbols per run instead of ~1000.
3. For the surviving candidates, fetch news, add it as one more voting
   factor, and aggregate: direction from the weighted sign, confidence from
   magnitude blended with how much of the weight agrees (not just a flat
   weighted sum), capped at 90%.
4. A signal that clears MIN_CONFIDENCE can still be VETOED: no valid ATR
   stop/target, poor risk:reward, or insufficient factor agreement.
5. Wait once (VERIFY_DELAY_SECONDS), then re-fetch + recompute all
   candidates in parallel ("double-check") before allowing a Telegram alert.
6. Respect a per-symbol cooldown so the same signal doesn't spam Telegram
   every scan cycle.
7. Write public/data/latest.json (consumed by the Next.js dashboard) and
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

from lib import bitkub_source, stock_source, indicators, news_source, scoring, state_store, telegram_notify, chart, price_target, positions_store, auto_trader, fundamentals, fear_greed
from lib.universe import STOCK_NAMES
from lib.scoring import Factor

MIN_CONFIDENCE = 70
VERIFY_DELAY_SECONDS = int(os.environ.get("VERIFY_DELAY_SECONDS", "45"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"
PRICE_FETCH_WORKERS = int(os.environ.get("PRICE_FETCH_WORKERS", "16"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(ROOT, "public", "data", "latest.json")
STATE_PATH = os.path.join(ROOT, "data", "state.json")
ALERT_SETTINGS_PATH = os.path.join(ROOT, "data", "alert_settings.json")
POSITIONS_PATH = os.path.join(ROOT, "data", "positions.json")
TRADE_LOG_PATH = os.path.join(ROOT, "data", "trade_log.json")


def load_alert_mode() -> str:
    """Which market(s) may trigger a Telegram alert: crypto/stock/both/none.

    Set via the dashboard's radio buttons (app/api/alert-settings), committed
    to ALERT_SETTINGS_PATH. Missing/invalid file or value falls back to
    "both" so a misconfiguration never silently kills all alerts.
    """
    try:
        with open(ALERT_SETTINGS_PATH, "r", encoding="utf-8") as f:
            mode = json.load(f).get("alert_mode")
    except (OSError, json.JSONDecodeError):
        return "both"
    return mode if mode in ("crypto", "stock", "both", "none") else "both"


def market_alerts_allowed(market: str, alert_mode: str) -> bool:
    if alert_mode == "none":
        return False
    if alert_mode in ("crypto", "stock"):
        return market == alert_mode
    return True


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


def technical_pass(item: dict, df, fundamentals_map: dict, fg_value: dict | None) -> dict:
    if item["market"] == "crypto":
        price = bitkub_source.get_last_price(item["ticker"], df)
        display_symbol = f"{item['ticker']}/THB"
    else:
        price = stock_source.get_last_price(item["ticker"], df)
        display_symbol = item["ticker"]

    base = {
        "market": item["market"],
        "raw_key": item["ticker"],
        "symbol": display_symbol,
        "display_name": item["name"],
        "price": price,
        "sparkline": chart.extract_sparkline(df),
    }

    # Fundamental/market-mood factors are crypto-only (stocks have no
    # supply concept and Fear & Greed tracks crypto sentiment specifically).
    is_crypto = item["market"] == "crypto"
    factors = indicators.compute_factors(
        df,
        fundamentals=fundamentals_map.get(item["ticker"].upper()) if is_crypto else None,
        fear_greed=fg_value if is_crypto else None,
    )
    if not factors:
        # Fewer than MIN_CANDLES bars available — no directional view, not a
        # weak guess (QuantDesk calls this ABSTAIN).
        return {**base, "factors": [], "atr": None, "price_target": None, "abstain": True}

    atr = indicators.compute_atr(df)
    direction_hint = scoring.aggregate(factors)["direction"]
    target = price_target.estimate_price_target(df, direction_hint, price, market=item["market"])

    return {**base, "factors": factors, "atr": atr, "price_target": target, "abstain": False}


def finalize(partial: dict, news_score_signed: float | None, news_reasons: list[str]) -> dict:
    """Combine technical factors (+ news, if available) into a final
    direction/confidence/agreement, apply veto rules, and build the
    human-readable reasons list, sorted by how much each factor mattered."""
    tech_factors = partial["factors"]
    all_factors = list(tech_factors)
    if news_score_signed is not None:
        all_factors.append(Factor(
            "news", news_score_signed / 100.0, scoring.WEIGHTS["news"],
            news_reasons[0] if news_reasons else "ข่าว",
        ))

    agg = scoring.aggregate(all_factors)
    tech_only_agg = scoring.aggregate(tech_factors)

    stop_target = scoring.compute_stop_target(agg["direction"], partial["price"], partial["atr"])
    veto_reason = scoring.check_veto(agreement=agg["agreement"], rr=stop_target["rr"] if stop_target else None)

    reasons = [f.detail for f in sorted(all_factors, key=lambda f: -abs(f.contribution))]
    if news_score_signed is None and news_reasons:
        reasons.append(news_reasons[0])
    if veto_reason:
        reasons.append(veto_reason)

    return {
        **{k: v for k, v in partial.items() if k != "factors"},
        "direction": agg["direction"],
        "confidence": agg["confidence"],
        "agreement": agg["agreement"],
        "technical_score": tech_only_agg["score"] * 100,
        "news_score": news_score_signed if news_score_signed is not None else 0.0,
        "stop_loss": stop_target["stop"] if stop_target else None,
        "risk_reward": stop_target["rr"] if stop_target else None,
        "reasons": reasons,
        "vetoed": veto_reason is not None,
    }


def make_abstain_result(partial: dict) -> dict:
    return {
        **{k: v for k, v in partial.items() if k != "factors"},
        "direction": "BUY",
        "confidence": 0.0,
        "agreement": 0.0,
        "technical_score": 0.0,
        "news_score": 0.0,
        "stop_loss": None,
        "risk_reward": None,
        "reasons": ["ข้อมูลราคาน้อยกว่า 60 แท่ง จึงไม่สามารถวิเคราะห์ได้ (ABSTAIN)"],
        "vetoed": True,
    }


def add_news_and_score(partial: dict) -> dict:
    query = f"{partial['display_name']} {'crypto' if partial['market'] == 'crypto' else 'stock'}"
    news_ticker = partial["raw_key"] if partial["market"] == "stock" else None
    news_score_signed, news_reasons, count = news_source.compute_news_score(query, ticker=news_ticker)
    # Missing news is treated as ABSENT (the factor is omitted, shrinking
    # coverage), not as a neutral vote — a symbol nobody wrote about is not
    # the same evidence as one with genuinely neutral headlines.
    news_value = news_score_signed if count > 0 else None
    return finalize(partial, news_value, news_reasons)


def add_without_news(partial: dict) -> dict:
    return finalize(partial, None, [])


def scan_universe(universe: list[dict], fundamentals_map: dict, fg_value: dict | None) -> list[dict]:
    technical_results = []
    with ThreadPoolExecutor(max_workers=PRICE_FETCH_WORKERS) as pool:
        futures = [pool.submit(fetch_price_data, item) for item in universe]
        for future in as_completed(futures):
            result = future.result()
            if result is None:
                continue
            item, df = result
            try:
                technical_results.append(technical_pass(item, df, fundamentals_map, fg_value))
            except Exception as exc:
                print(f"[technical] {item['market']}:{item['ticker']} failed: {exc}")

    print(f"Priced {len(technical_results)}/{len(universe)} symbols.")

    abstained = [r for r in technical_results if r["abstain"]]
    active = [r for r in technical_results if not r["abstain"]]

    needs_news, skipped = [], []
    for r in active:
        best_case = scoring.best_case_confidence(r["factors"])
        (needs_news if best_case >= MIN_CONFIDENCE else skipped).append(r)
    print(
        f"{len(needs_news)}/{len(active)} active symbol(s) cleared the technical prefilter, "
        f"fetching news for those... ({len(abstained)} abstained for insufficient data)"
    )

    scored = []
    for partial in needs_news:
        scored.append(add_news_and_score(partial))
        time.sleep(0.3)
    for partial in skipped:
        scored.append(add_without_news(partial))
    for partial in abstained:
        scored.append(make_abstain_result(partial))

    return scored


def reverify_candidates(candidates: list[dict], fundamentals_map: dict, fg_value: dict | None) -> list[dict]:
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
        partial = technical_pass(item, df, fundamentals_map, fg_value)
        if partial["abstain"]:
            return make_abstain_result(partial)
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
    positions = positions_store.load_positions(POSITIONS_PATH)
    alert_mode = load_alert_mode()
    print(f"Alert mode: {alert_mode}")
    universe = build_universe()
    print(f"Universe: {sum(1 for u in universe if u['market'] == 'crypto')} crypto, "
          f"{sum(1 for u in universe if u['market'] == 'stock')} stocks.")

    # Fetched once per scan cycle, not once per symbol — see
    # lib/fundamentals.py and lib/fear_greed.py for why.
    fundamentals_map = fundamentals.get_fundamentals_map()
    fg_value = fear_greed.get_fear_greed()
    print(f"Fundamentals: {len(fundamentals_map)} symbol(s) cached. "
          f"Fear & Greed: {fg_value['value'] if fg_value else 'unavailable'}.")

    results = scan_universe(universe, fundamentals_map, fg_value)

    by_key = {(r["market"], r["raw_key"]): i for i, r in enumerate(results)}
    candidates = [r for r in results if r["confidence"] >= MIN_CONFIDENCE and not r.get("vetoed")]
    print(f"{len(candidates)} candidate(s) crossed {MIN_CONFIDENCE}% and survived veto checks on first pass.")

    alerts_sent = 0
    for original, verified in reverify_candidates(candidates, fundamentals_map, fg_value):
        key = f"{verified['market']}:{verified['raw_key']}"

        if verified["confidence"] < MIN_CONFIDENCE or verified["direction"] != original["direction"] or verified.get("vetoed"):
            print(f"[verify] {verified['symbol']} did not hold up on re-check (vetoed={verified.get('vetoed')}), not alerting")
            continue

        idx = by_key.get((verified["market"], verified["raw_key"]))
        if idx is not None:
            verified["verified"] = True
            results[idx] = verified

        if not market_alerts_allowed(verified["market"], alert_mode):
            print(f"[alert-mode] {verified['symbol']} suppressed (alert_mode={alert_mode})")
        elif state_store.should_alert(state, key, verified["direction"], verified["confidence"]):
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

    trades = auto_trader.run(results, positions)
    for trade in trades:
        positions_store.append_trade_log(TRADE_LOG_PATH, trade)
    positions_store.save_positions(POSITIONS_PATH, positions)

    for r in results:
        r.pop("raw_key", None)

    crypto_count = sum(1 for u in universe if u["market"] == "crypto")
    stock_count = sum(1 for u in universe if u["market"] == "stock")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "Automated technical + news-sentiment signals. Not financial advice. Educational use only.",
        "min_confidence_threshold": MIN_CONFIDENCE,
        "watchlist_counts": {"crypto": crypto_count, "stock": stock_count},
        "signals": results,
        "open_positions": positions,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    state_store.save_state(STATE_PATH, state)
    print(f"Done. {len(results)} symbols scanned, {alerts_sent} Telegram alert(s) sent, {len(trades)} auto-trade(s) executed.")


if __name__ == "__main__":
    main()
