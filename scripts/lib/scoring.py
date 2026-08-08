"""Combine technical + news scores into a single confidence-scored signal."""
from __future__ import annotations

TECH_WEIGHT = 0.65
NEWS_WEIGHT = 0.35


def combine_scores(technical_score: float, news_score: float) -> tuple[str, float]:
    """Returns (direction, confidence 0-100)."""
    combined = TECH_WEIGHT * technical_score + NEWS_WEIGHT * news_score
    direction = "BUY" if combined >= 0 else "SELL"
    confidence = abs(combined)
    return direction, confidence
