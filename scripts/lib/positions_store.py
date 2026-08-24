"""Tracks open auto-trade positions and an append-only trade log.

Positions persist in data/positions.json (committed by the GitHub Action,
same pattern as data/state.json) so take-profit/stop-loss tracking survives
across stateless Action runs. data/trade_log.json is an audit trail of every
executed buy/sell — the bot never reads it back, it's for the user to review.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

MAX_TRADE_LOG_ENTRIES = 500


def load_positions(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_positions(path: str, positions: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2, ensure_ascii=False)


def open_position(positions: dict, ticker: str, *, cost_thb: float, coin_amount: float,
                   order_id: str | None, confidence: float) -> None:
    positions[ticker] = {
        "entry_price": cost_thb / coin_amount,
        "cost_thb": cost_thb,
        "coin_amount": coin_amount,
        "order_id": order_id,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "buy_confidence": confidence,
    }


def close_position(positions: dict, ticker: str) -> dict | None:
    return positions.pop(ticker, None)


def load_trade_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def append_trade_log(path: str, entry: dict) -> None:
    log = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            log = json.load(f)
    log.append({**entry, "at": datetime.now(timezone.utc).isoformat()})
    log = log[-MAX_TRADE_LOG_ENTRIES:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
