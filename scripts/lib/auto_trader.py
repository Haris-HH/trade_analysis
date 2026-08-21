"""Auto-trading engine: turns the same indicator-driven signals that power
Telegram alerts into real Bitkub market orders.

- BUY: a crypto symbol that survived the double-check re-verification pass
  (scripts/main.py's reverify_candidates — the exact same pipeline used for
  Telegram "BUY NOW" alerts, built on scripts/lib/indicators.py +
  scoring.py's regime-aware confluence engine), with confidence >=
  MIN_CONFIDENCE and not vetoed. Only opens a position if that ticker isn't
  already held and MAX_POSITIONS isn't already reached.
- SELL: every open position is checked against the *current* scan cycle's
  price (no re-verification needed for an exit) and closed automatically at
  TAKE_PROFIT_PCT gain or STOP_LOSS_PCT loss, whichever comes first.

Disabled by default: AUTO_TRADE_ENABLED must be exactly "1", so real money
is only ever risked once the user opts in explicitly with their own Bitkub
API credentials. Even when enabled, DRY_RUN (the same flag scripts/main.py
already uses for Telegram) logs the orders that *would* be placed instead of
sending them to Bitkub — use it to validate behavior before going live.
"""
from __future__ import annotations

import os

from . import bitkub_trade, positions_store, telegram_notify


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


def _try_close(ticker: str, position: dict, price: float, reason: str) -> dict | None:
    pnl_pct = (price - position["entry_price"]) / position["entry_price"]
    try:
        if DRY_RUN:
            proceeds_thb, order_id = position["coin_amount"] * price, "dry-run"
        else:
            result = bitkub_trade.place_market_sell(ticker, position["coin_amount"])
            proceeds_thb = float(result.get("rec", position["coin_amount"] * price))
            order_id = result.get("id")
    except Exception as exc:
        print(f"[auto-trade] SELL {ticker} failed: {exc}")
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


def _try_open(ticker: str, price: float, confidence: float) -> dict | None:
    try:
        if DRY_RUN:
            coin_amount, order_id = TRADE_AMOUNT_THB / price, "dry-run"
        else:
            result = bitkub_trade.place_market_buy(ticker, TRADE_AMOUNT_THB)
            coin_amount = float(result.get("rec", 0))
            order_id = result.get("id")
        if coin_amount <= 0:
            print(f"[auto-trade] BUY {ticker} returned zero coin amount, skipping")
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
        price = prices.get(ticker)
        if price is None:
            continue
        position = positions[ticker]
        pnl_pct = (price - position["entry_price"]) / position["entry_price"]
        if pnl_pct >= TAKE_PROFIT_PCT:
            reason = f"take-profit +{pnl_pct:.1%}"
        elif STOP_LOSS_PCT > 0 and pnl_pct <= -STOP_LOSS_PCT:
            reason = f"stop-loss {pnl_pct:.1%}"
        else:
            continue
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
                trades.append(trade)

    return trades
