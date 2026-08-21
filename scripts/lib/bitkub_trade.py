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


def _signed_request(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
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
    result = resp.json()
    if result.get("error", 0) != 0:
        raise BitkubAPIError(result["error"], str(result.get("result", result)), path)
    return result["result"]


def place_market_buy(ticker: str, amount_thb: float, client_id: str | None = None) -> dict:
    """Market-buy `amount_thb` worth of `ticker` (e.g. "BTC") against THB.

    Returns Bitkub's order result, including `rec` — the coin amount actually
    received net of fees, which is what the caller should record as the
    position size (not amount_thb / current price)."""
    body = {"sym": f"{ticker.lower()}_thb", "amt": round(amount_thb, 2), "rat": 0, "typ": "market"}
    if client_id:
        body["client_id"] = client_id
    return _signed_request("POST", "/api/v3/market/place-bid", body=body)


def place_market_sell(ticker: str, amount_coin: float, client_id: str | None = None) -> dict:
    """Market-sell `amount_coin` units of `ticker` back to THB.

    Returns Bitkub's order result, including `rec` — the THB actually
    received net of fees."""
    body = {"sym": f"{ticker.lower()}_thb", "amt": round(amount_coin, 8), "rat": 0, "typ": "market"}
    if client_id:
        body["client_id"] = client_id
    return _signed_request("POST", "/api/v3/market/place-ask", body=body)


def get_order_info(ticker: str, order_id: str, side: str) -> dict:
    """side: "buy" or "sell". Useful for manually double-checking a fill;
    not called by the auto-trader itself (place-bid/place-ask already
    return the filled amount for a market order)."""
    params = {"sym": f"{ticker.lower()}_thb", "id": order_id, "sd": side}
    return _signed_request("GET", "/api/v3/market/order-info", params=params)


def get_order_history(ticker: str, limit: int = 10) -> list:
    """Read-only — past filled/cancelled orders for `ticker`_THB. Not called
    by the auto-trader; useful for manually auditing trades or, with an
    empty/near-empty account, as a safe way to confirm API credentials and
    the HMAC signature are being accepted without risking any funds."""
    params = {"sym": f"{ticker.lower()}_thb", "lmt": limit}
    return _signed_request("GET", "/api/v3/market/my-order-history", params=params)
