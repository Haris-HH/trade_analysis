"""Tracks alert cooldowns and last known signal per symbol.

Committed back to the repo by the GitHub Action so state persists across
scheduled runs (GitHub Actions runners are stateless between jobs).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

COOLDOWN_HOURS = 4
RE_ALERT_CONFIDENCE_JUMP = 10  # re-alert earlier if confidence jumps by this much


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def should_alert(state: dict, key: str, direction: str, confidence: float) -> bool:
    entry = state.get(key)
    if entry is None:
        return True
    if entry.get("direction") != direction:
        return True
    last_alert = entry.get("last_alert_at")
    if not last_alert:
        return True
    elapsed_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(last_alert)).total_seconds() / 3600
    if elapsed_hours >= COOLDOWN_HOURS:
        return True
    if confidence - entry.get("confidence", 0) >= RE_ALERT_CONFIDENCE_JUMP:
        return True
    return False


def record_alert(state: dict, key: str, direction: str, confidence: float) -> None:
    state[key] = {
        "direction": direction,
        "confidence": confidence,
        "last_alert_at": datetime.now(timezone.utc).isoformat(),
    }
