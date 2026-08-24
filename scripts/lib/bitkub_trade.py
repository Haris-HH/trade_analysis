"""Authenticated Bitkub v3 REST client for placing real market orders.

Used only by scripts/lib/auto_trader.py to execute BUY/SELL orders once a
signal clears the auto-trade bar. Every authenticated request is HMAC-SHA256
signed per Bitkub's spec (timestamp from /api/v3/servertime to avoid clock
drift rejecting the signature):
https://github.com/bitkub/bitkub-official-api-docs/blob/master/restful-api.md

Requires BITKUB_API_KEY / BITKUB_API_SECRET in the environment. Create the
key at bitkub.com under API Management, scoped to "Trade" permission only —
never enable withdrawal on a key used by an automated bot.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from urllib.parse import urlencode

import requests

from . import bitkub_source

BASE_URL = "https://api.bitkub.com"
HEADERS_BASE = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}


class BitkubAPIError(RuntimeError):
    def __init__(self, code: int, message: str, endpoint: str):
        super().__init__(f"Bitkub API error {code} on {endpoint}: {message}")
        self.code = code


def _api_key() -> str:
    key = os.environ.get("BITKUB_API_KEY")
    if not key:
        raise RuntimeError("BITKUB_API_KEY is not set")
    return key


def _api_secret() -> bytes:
    secret = os.environ.get("BITKUB_API_SECRET")
    if not secret:
        raise RuntimeError("BITKUB_API_SECRET is not set")
    return secret.encode()


def _server_time_ms() -> int:
    resp = requests.get(f"{BASE_URL}/api/v3/servertime", headers=HEADERS_BASE, timeout=10)
    resp.raise_for_status()
    return int(resp.text.strip())


def _sign(ts: int, method: str, path: str, payload: str) -> str:
    message = f"{ts}{method}{path}{payload}"
    return hmac.new(_api_secret(), message.encode(), hashlib.sha256).hexdigest()


def _signed_call(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
    """Shared HMAC-signed request plumbing for both v3 and v4 endpoints —
    the signing scheme (ts + method + path + payload) is identical between
    them, only the response envelope differs (v3: {error, result}, v4:
    {code, message, data}), so callers parse the raw JSON themselves."""
    ts = _server_time_ms()
    if method == "GET":
        query = f"?{urlencode(params)}" if params else ""
        payload = query
        data = None
    else:
        payload = json.dumps(body or {}, separators=(",", ":"))
        query = ""
        data = payload

    headers = {
        **HEADERS_BASE,
        "Content-Type": "application/json",
        "X-BTK-APIKEY": _api_key(),
        "X-BTK-TIMESTAMP": str(ts),
        "X-BTK-SIGN": _sign(ts, method, path, payload),
    }
    resp = requests.request(method, f"{BASE_URL}{path}{query}", headers=headers, data=data, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _signed_request(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
    result = _signed_call(method, path, params=params, body=body)
    if result.get("error", 0) != 0:
        raise BitkubAPIError(result["error"], str(result.get("result", result)), path)
    return result["result"]


def _signed_request_v4(method: str, path: str, *, params: dict | None = None, body: dict | None = None):
    """v4 endpoints (e.g. wallet/balances) use {code, message, data} instead
    of v3's {error, result} — code is the string "0" on success, an
    alphanumeric error code like "V1007-CW" otherwise."""
    result = _signed_call(method, path, params=params, body=body)
    if result.get("code") not in (0, "0"):
        raise BitkubAPIError(result.get("code"), result.get("message", str(result)), path)
    return result.get("data")


def place_market_buy(ticker: str, amount_thb: float, client_id: str | None = None) -> dict:
    """Market-buy `amount_thb` worth of `ticker` (e.g. "BTC") against THB.

    The immediate response does NOT reliably carry a filled-quantity field
    (verified 2026-08-21 against live orders — contradicts the `rec` field
    shown in Bitkub's own example docs, which real responses didn't have).
    Callers must look up the actual fill with resolve_fill() using the
    returned `id`."""
    body = {"sym": f"{ticker.lower()}_thb", "amt": round(amount_thb, 2), "rat": 0, "typ": "market"}
    if client_id:
        body["client_id"] = client_id
    return _signed_request("POST", "/api/v3/market/place-bid", body=body)


def place_market_sell(ticker: str, amount_coin: float, client_id: str | None = None) -> dict:
    """Market-sell `amount_coin` units of `ticker` back to THB. See
    place_market_buy's docstring — same caveat, use resolve_fill()."""
    body = {"sym": f"{ticker.lower()}_thb", "amt": round(amount_coin, 8), "rat": 0, "typ": "market"}
    if client_id:
        body["client_id"] = client_id
    return _signed_request("POST", "/api/v3/market/place-ask", body=body)


def place_limit_sell(ticker: str, amount_coin: float, rate: float, client_id: str | None = None) -> dict:
    """Rest a limit sell for `amount_coin` units of `ticker` at `rate` THB
    each. Used to place a take-profit order the instant a buy fills, so
    Bitkub's own matching engine catches the target the moment price
    crosses it instead of waiting for this bot's next 5-minute poll (which
    could miss a spike that reverses before the next check).

    `rate` is rounded to this pair's actual tick size (bitkub_source's
    price_scale, e.g. 2 decimal places for POL/BTC/ETH), not a flat 8
    decimals -- a rate that doesn't land on the tick size gets rejected
    outright (error 13/14: "Invalid rate"/"Improper rate"), which is what
    was silently breaking every take-profit order for coins with a coarser
    price scale than 8."""
    rate = round(rate, bitkub_source.get_price_scale(ticker))
    body = {"sym": f"{ticker.lower()}_thb", "amt": round(amount_coin, 8), "rat": rate, "typ": "limit"}
    if client_id:
        body["client_id"] = client_id
    return _signed_request("POST", "/api/v3/market/place-ask", body=body)


def cancel_order(ticker: str, order_id: str, side: str) -> dict:
    """side: "buy" or "sell". Cancels a resting (unfilled or
    partially-filled) order — used to pull a resting take-profit limit
    sell before a stop-loss market sell, so the two can never both try to
    sell the same coins out from under each other."""
    body = {"sym": f"{ticker.lower()}_thb", "id": order_id, "sd": side}
    return _signed_request("POST", "/api/v3/market/cancel-order", body=body)


def get_order_info(ticker: str, order_id: str, side: str) -> dict:
    """side: "buy" or "sell". Authoritative order status/fills, including a
    `history` list of individual fills — this is what resolve_fill() reads.
    `status` is one of "filled" / "unfilled" / "cancelled"."""
    params = {"sym": f"{ticker.lower()}_thb", "id": order_id, "sd": side}
    return _signed_request("GET", "/api/v3/market/order-info", params=params)


def resolve_fill(ticker: str, order_id: str, side: str) -> dict | None:
    """Authoritative fill amounts for a market order, from order-info's
    `history` (verified against a live filled buy: each fill's `amount` is
    in the currency the order was placed in — THB for a buy, coin for a
    sell — with `rate` the fill price; a buy's `amount` already nets out
    that fill's fee, e.g. a 100 THB order with 0.25 THB fee showed
    `amount: 99.75`).

    Returns None if the order has no fills yet (caller should retry) —
    never raises for that case, since a market order that already returned
    error=0 has definitely spent/received money and must not be silently
    dropped."""
    info = get_order_info(ticker, order_id, side)
    history = info.get("history") or []
    if not history:
        return None
    if side == "buy":
        thb = sum(float(h["amount"]) for h in history)
        coin = sum(float(h["amount"]) / float(h["rate"]) for h in history if h.get("rate"))
    else:
        coin = sum(float(h["amount"]) for h in history)
        thb = sum(float(h["amount"]) * float(h["rate"]) - float(h.get("fee", 0)) for h in history if h.get("rate"))
    if coin <= 0:
        return None
    return {"coin": coin, "thb": thb}


def get_order_history(ticker: str, limit: int = 10) -> list:
    """Read-only — past filled/cancelled orders for `ticker`_THB. Not called
    by the auto-trader; useful for manually auditing trades or, with an
    empty/near-empty account, as a safe way to confirm API credentials and
    the HMAC signature are being accepted without risking any funds."""
    params = {"sym": f"{ticker.lower()}_thb", "lmt": limit}
    return _signed_request("GET", "/api/v3/market/my-order-history", params=params)


def get_wallet_balances() -> dict[str, float]:
    """{currency: available_amount} for every currency in the account
    (v3's market/wallet and market/balances were deprecated and removed
    2026-05-26 — this is their v4 replacement). Used to verify a tracked
    position is still actually held before trying to sell it, rather than
    retrying a doomed sell forever if it was already sold manually outside
    the bot (see 2026-08-22: LINK/DYDX/EIGEN/TAO/UNI/XPL desync)."""
    data = _signed_request_v4("GET", "/api/v4/wallet/balances") or []
    return {row["currency"]: float(row["available"]) for row in data}
