"""Auto-trading engine: turns the same indicator-driven signals that power
Telegram alerts into real Bitkub market orders.

- BUY: a crypto symbol that survived the double-check re-verification pass
  (scripts/main.py's reverify_candidates — the exact same pipeline used for
  Telegram "BUY NOW" alerts, built on scripts/lib/indicators.py +
  scoring.py's regime-aware confluence engine), with confidence >=
  MIN_CONFIDENCE and not vetoed. Only opens a position if that ticker isn't
  already held and MAX_POSITIONS isn't already reached.
- SELL: a resting limit sell at the TAKE_PROFIT_PCT target is placed the
  moment a position opens (and backfilled for any position missing one),
  so Bitkub's own matching engine can catch it between polls instead of
  this bot only noticing up to 5 minutes late. Every open position is also
  checked against the *current* scan cycle's price for STOP_LOSS_PCT (which
  cancels the resting order first, since a market exit and a limit order
  must never both be live for the same coins) and, if no resting order
  exists, as a take-profit fallback too.

Disabled by default: AUTO_TRADE_ENABLED must be exactly "1", so real money
is only ever risked once the user opts in explicitly with their own Bitkub
API credentials. Even when enabled, DRY_RUN (the same flag scripts/main.py
already uses for Telegram) logs the orders that *would* be placed instead of
sending them to Bitkub — use it to validate behavior before going live.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from . import bitkub_source, bitkub_trade, positions_store, telegram_notify

FILL_RETRY_ATTEMPTS = 4
FILL_RETRY_DELAY_SECONDS = 1.5

# A stuck position (e.g. broker-routed coin rejecting sell orders) gets
# retried silently every scan cycle — re-notifying on every single retry
# would spam Telegram every 5 minutes, so only re-alert this often.
SELL_FAILURE_NOTIFY_COOLDOWN_SECONDS = 6 * 3600


def _env_float(name: str, default: float) -> float:
    # A GitHub Actions secret that was never set still shows up as an env
    # var with an EMPTY STRING value, not a missing key — os.environ.get's
    # default only kicks in when the key is absent entirely, so an empty
    # string here must be treated the same as unset or float("") crashes.
    val = os.environ.get(name)
    return float(val) if val else default


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    return int(val) if val else default


ENABLED = os.environ.get("AUTO_TRADE_ENABLED") == "1"
DRY_RUN = os.environ.get("DRY_RUN") == "1"
TRADE_AMOUNT_THB = _env_float("AUTO_TRADE_AMOUNT_THB", 100)
MAX_POSITIONS = _env_int("AUTO_TRADE_MAX_POSITIONS", 3)
MIN_CONFIDENCE = _env_float("AUTO_TRADE_MIN_CONFIDENCE", 75)
TAKE_PROFIT_PCT = _env_float("AUTO_TRADE_TAKE_PROFIT_PCT", 5) / 100
STOP_LOSS_PCT = _env_float("AUTO_TRADE_STOP_LOSS_PCT", 8) / 100


def _fmt(v: float) -> str:
    return f"{v:,.4f}" if v < 10 else f"{v:,.2f}"


def _notify(text: str) -> None:
    if DRY_RUN:
        # Windows consoles on non-UTF-8 codepages (e.g. Thai cp874) can't
        # encode some Thai characters or the emoji marker — never let a local
        # dry-run crash on a print(), just fall back to a lossy rendering.
        try:
            print("[auto-trade][dry-run] would send Telegram message:\n" + text)
        except UnicodeEncodeError:
            print("[auto-trade][dry-run] would send Telegram message (non-ASCII chars omitted):\n"
                  + text.encode("ascii", "replace").decode("ascii"))
        return
    telegram_notify.send_telegram_message(text)


def _current_prices(results: list[dict]) -> dict[str, float]:
    return {r["raw_key"]: r["price"] for r in results if r["market"] == "crypto" and r.get("price")}


def _resolve_fill(ticker: str, order_id: str | None, side: str, fallback: dict) -> dict:
    """Poll order-info for the authoritative fill (place-bid/ask's own
    response doesn't reliably carry it — see bitkub_trade.resolve_fill).
    Falls back to a price-based estimate, loudly, rather than ever treating
    a successfully placed order (money already moved) as if it never
    happened — that silent-drop is exactly what left real buys untracked
    on 2026-08-21."""
    if order_id:
        for attempt in range(FILL_RETRY_ATTEMPTS):
            try:
                fill = bitkub_trade.resolve_fill(ticker, order_id, side)
                if fill:
                    return fill
            except Exception as exc:
                print(f"[auto-trade] order-info lookup for {ticker} {order_id} failed (attempt {attempt + 1}): {exc}")
            if attempt < FILL_RETRY_ATTEMPTS - 1:
                time.sleep(FILL_RETRY_DELAY_SECONDS)
    print(f"[auto-trade] WARNING: could not confirm fill for {ticker} order {order_id} — "
          f"using a price-based estimate, VERIFY ON BITKUB MANUALLY")
    return fallback


def _describe_sell_failure(exc: Exception, ticker: str) -> str:
    """Translate a raw Bitkub exception into something a non-engineer can
    act on. Error 61 ("broker" coins reject place-ask outright — see
    bitkub_source.is_broker_sourced) is the one confirmed recurring cause;
    everything else is surfaced as-is since we haven't seen it happen yet."""
    if isinstance(exc, bitkub_trade.BitkubAPIError) and exc.code == 61:
        return (
            f"Bitkub routes {ticker} through its \"broker\" order book, which rejects "
            f"sell orders outright (error 61) — this can't be closed automatically. "
            f"Please sell it manually in the Bitkub app; the bot will keep watching and "
            f"retrying every cycle until it succeeds."
        )
    return str(exc)


def _try_close(ticker: str, position: dict, price: float, reason: str) -> dict | None:
    pnl_pct = (price - position["entry_price"]) / position["entry_price"]
    try:
        if DRY_RUN:
            proceeds_thb, order_id = position["coin_amount"] * price, "dry-run"
        else:
            result = bitkub_trade.place_market_sell(ticker, position["coin_amount"])
            order_id = result.get("id")
            fill = _resolve_fill(ticker, order_id, "sell", {"thb": position["coin_amount"] * price})
            proceeds_thb = fill["thb"]
    except Exception as exc:
        print(f"[auto-trade] SELL {ticker} failed: {exc}")
        # A failed sell isn't a one-off — it retries every scan cycle until
        # it succeeds or the user intervenes manually, so notify (rate-limited)
        # instead of leaving this only visible in a CI log nobody can reach.
        last_notified = position.get("sell_failure_notified_at")
        now = datetime.now(timezone.utc)
        stale = not last_notified or (
            now - datetime.fromisoformat(last_notified)
        ).total_seconds() >= SELL_FAILURE_NOTIFY_COOLDOWN_SECONDS
        if stale:
            _notify(
                f"⚠️ <b>Auto-trade SELL failed</b> ({reason})\n"
                f"{ticker}/THB — target hit ({pnl_pct:+.2%}) but the sell order was rejected:\n"
                f"{_describe_sell_failure(exc, ticker)}"
            )
            position["sell_failure_notified_at"] = now.isoformat()
        return None

    pnl_thb = proceeds_thb - position["cost_thb"]
    _notify(
        f"\U0001f916 <b>Auto-trade SELL</b> ({reason})\n"
        f"{ticker}/THB — {position['coin_amount']:.8f} {ticker}\n"
        f"เข้า {_fmt(position['entry_price'])} → ออก {_fmt(price)} ({pnl_pct:+.2%})\n"
        f"กำไร/ขาดทุน: {pnl_thb:+,.2f} THB"
    )
    print(f"[auto-trade] SELL {ticker} ({reason}) pnl={pnl_pct:+.2%} ({pnl_thb:+,.2f} THB)")
    return {
        "ticker": ticker, "side": "sell", "reason": reason, "price": price,
        "pnl_pct": pnl_pct, "pnl_thb": pnl_thb, "order_id": order_id,
    }


def _place_resting_tp_order(ticker: str, position: dict) -> None:
    """Rest a limit sell at the take-profit target so Bitkub's matching
    engine can fill it the instant price crosses, rather than this bot
    only ever noticing up to 5 minutes late. Best-effort: on failure (e.g.
    a broker-routed coin rejecting the order, same as place_market_sell)
    the position simply falls back to the price-poll check below, same as
    before this existed."""
    tp_price = position["entry_price"] * (1 + TAKE_PROFIT_PCT)
    try:
        result = bitkub_trade.place_limit_sell(ticker, position["coin_amount"], tp_price)
        position["tp_order_id"] = result.get("id")
        print(f"[auto-trade] resting take-profit sell placed for {ticker} at {tp_price} (order {position['tp_order_id']})")
    except Exception as exc:
        print(f"[auto-trade] could not place resting take-profit order for {ticker}: {exc} — falling back to the 5-min poll")


def _cancel_resting_tp_order(ticker: str, position: dict) -> None:
    order_id = position.pop("tp_order_id", None)
    if not order_id:
        return
    try:
        bitkub_trade.cancel_order(ticker, order_id, "sell")
        print(f"[auto-trade] cancelled resting take-profit order {order_id} for {ticker} to proceed with stop-loss")
    except Exception as exc:
        print(f"[auto-trade] failed to cancel resting take-profit order {order_id} for {ticker}: {exc}")


def _check_resting_tp_fill(ticker: str, position: dict) -> dict | None:
    """Returns a trade record if the resting take-profit limit order has
    fully filled. Deliberately ignores partial fills (rare at these order
    sizes) rather than half-closing a position's bookkeeping — a partial
    fill just keeps waiting here until it either finishes or stop-loss
    cancels the remainder."""
    order_id = position.get("tp_order_id")
    if not order_id:
        return None
    try:
        info = bitkub_trade.get_order_info(ticker, order_id, "sell")
    except Exception as exc:
        print(f"[auto-trade] order-info check for {ticker} TP order {order_id} failed: {exc}")
        return None
    if info.get("status") != "filled":
        return None
    fill = bitkub_trade.resolve_fill(ticker, order_id, "sell")
    if not fill or fill["coin"] <= 0:
        return None

    proceeds_thb = fill["thb"]
    avg_rate = proceeds_thb / fill["coin"]
    pnl_pct = (avg_rate - position["entry_price"]) / position["entry_price"]
    pnl_thb = proceeds_thb - position["cost_thb"]
    reason = "take-profit (resting order)"
    _notify(
        f"\U0001f916 <b>Auto-trade SELL</b> ({reason})\n"
        f"{ticker}/THB — {fill['coin']:.8f} {ticker}\n"
        f"เข้า {_fmt(position['entry_price'])} → ออก {_fmt(avg_rate)} ({pnl_pct:+.2%})\n"
        f"กำไร/ขาดทุน: {pnl_thb:+,.2f} THB"
    )
    print(f"[auto-trade] SELL {ticker} ({reason}) pnl={pnl_pct:+.2%} ({pnl_thb:+,.2f} THB)")
    return {
        "ticker": ticker, "side": "sell", "reason": reason, "price": avg_rate,
        "pnl_pct": pnl_pct, "pnl_thb": pnl_thb, "order_id": order_id,
    }


def _try_open(ticker: str, price: float, confidence: float) -> dict | None:
    try:
        if DRY_RUN:
            coin_amount, order_id = TRADE_AMOUNT_THB / price, "dry-run"
        else:
            result = bitkub_trade.place_market_buy(ticker, TRADE_AMOUNT_THB)
            order_id = result.get("id")
            fill = _resolve_fill(ticker, order_id, "buy", {"coin": TRADE_AMOUNT_THB / price})
            coin_amount = fill["coin"]
        if coin_amount <= 0:
            print(f"[auto-trade] BUY {ticker} filled for zero coin, skipping")
            return None
    except Exception as exc:
        print(f"[auto-trade] BUY {ticker} failed: {exc}")
        return None

    _notify(
        f"\U0001f916 <b>Auto-trade BUY</b>\n"
        f"{ticker}/THB — {TRADE_AMOUNT_THB:,.2f} THB @ {_fmt(price)} "
        f"(ความมั่นใจ {confidence:.0f}%)\n"
        f"TP +{TAKE_PROFIT_PCT:.0%} / SL -{STOP_LOSS_PCT:.0%}"
    )
    print(f"[auto-trade] BUY {ticker} {TRADE_AMOUNT_THB} THB @ {price} conf={confidence:.0f}%")
    return {
        "ticker": ticker, "side": "buy", "price": price, "cost_thb": TRADE_AMOUNT_THB,
        "coin_amount": coin_amount, "order_id": order_id, "confidence": confidence,
    }


def run(results: list[dict], positions: dict) -> list[dict]:
    """Mutates `positions` in place. Returns executed trade records (for the
    trade log). No-op entirely unless AUTO_TRADE_ENABLED == "1"."""
    if not ENABLED:
        return []

    prices = _current_prices(results)
    trades: list[dict] = []

    # 1) Exits first, so a closed position frees a slot for a fresh entry
    #    in the same cycle instead of waiting for the next scan.
    for ticker in list(positions.keys()):
        position = positions[ticker]

        # Backfill a resting take-profit order for any position that
        # doesn't have one yet (opened before this feature existed, or an
        # earlier placement attempt failed) instead of only ever placing
        # one for brand-new buys.
        if not DRY_RUN and not position.get("tp_order_id"):
            _place_resting_tp_order(ticker, position)

        if position.get("tp_order_id") and not DRY_RUN:
            trade = _check_resting_tp_fill(ticker, position)
            if trade:
                positions_store.close_position(positions, ticker)
                trades.append(trade)
                continue

        price = prices.get(ticker)
        if price is None:
            continue
        pnl_pct = (price - position["entry_price"]) / position["entry_price"]
        if pnl_pct >= TAKE_PROFIT_PCT and not position.get("tp_order_id"):
            # Only take the market-sell TP path when there's no resting
            # limit order already covering this — otherwise we'd race our
            # own order and the second sell would fail on insufficient
            # balance.
            reason = f"take-profit +{pnl_pct:.1%}"
        elif STOP_LOSS_PCT > 0 and pnl_pct <= -STOP_LOSS_PCT:
            reason = f"stop-loss {pnl_pct:.1%}"
        else:
            continue

        if reason.startswith("stop-loss") and position.get("tp_order_id"):
            _cancel_resting_tp_order(ticker, position)

        trade = _try_close(ticker, position, price, reason)
        if trade:
            positions_store.close_position(positions, ticker)
            trades.append(trade)

    # 2) Entries — only symbols that cleared the same double-check
    #    re-verification pass used for Telegram BUY-NOW alerts.
    if len(positions) < MAX_POSITIONS:
        candidates = [
            r for r in results
            if r["market"] == "crypto"
            and r.get("verified")
            and r["direction"] == "BUY"
            and not r.get("vetoed")
            and r["confidence"] >= MIN_CONFIDENCE
            # "broker"-sourced coins are priced/listed normally but Bitkub's
            # place-bid/place-ask reject them outright (error 61) — confirmed
            # 2026-08-21 for BONK/FLOKI/NEIRO/BOME/BRETT.
            and not bitkub_source.is_broker_sourced(r["raw_key"])
        ]
        candidates.sort(key=lambda r: -r["confidence"])
        for r in candidates:
            if len(positions) >= MAX_POSITIONS:
                break
            ticker = r["raw_key"]
            if ticker in positions:
                continue
            trade = _try_open(ticker, r["price"], r["confidence"])
            if trade:
                positions_store.open_position(
                    positions, ticker,
                    cost_thb=trade["cost_thb"], coin_amount=trade["coin_amount"],
                    order_id=trade["order_id"], confidence=trade["confidence"],
                )
                # Rest the take-profit sell immediately, not on the next
                # cycle, so a fast spike right after entry doesn't need to
                # wait up to 5 minutes for this bot to notice it.
                if not DRY_RUN:
                    _place_resting_tp_order(ticker, positions[ticker])
                trades.append(trade)

    return trades
