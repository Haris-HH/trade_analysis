"""Alternative.me's Fear & Greed Index: a market-wide crypto sentiment
gauge (0 = extreme fear, 100 = extreme greed), used as a contrarian
mean-reversion factor per the risk-management checklist's "วัดอารมณ์ตลาด
(Fear and Greed Index) ว่าช่วงนั้นคนโลภหรือกลัวมากเกินไป" — extreme fear
tilts toward BUY (be greedy when others are fearful), extreme greed tilts
toward caution.

One HTTP call per scan cycle (not per symbol) — the index only updates
once a day, so calling it more often buys nothing, and this keeps the
~950-symbol scan from adding 950 extra requests for a single shared value.
"""
from __future__ import annotations

import requests

URL = "https://api.alternative.me/fng/?limit=1"
TIMEOUT = 8


def get_fear_greed() -> dict | None:
    """Returns {"value": 0-100, "classification": str} or None on failure —
    callers treat None as "no market-mood opinion this cycle", same
    ABSTAIN-style pattern as every other optional factor."""
    try:
        resp = requests.get(URL, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()["data"][0]
        return {"value": int(data["value"]), "classification": data["value_classification"]}
    except Exception as exc:
        print(f"[fear-greed] fetch failed, skipping market-mood factor this cycle: {exc}")
        return None
