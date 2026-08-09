"""Compact price-series extraction for the dashboard's on-card sparkline chart."""
from __future__ import annotations

import numpy as np
import pandas as pd


def extract_sparkline(df: pd.DataFrame, points: int = 60) -> list[float]:
    """Downsample df['close'] to at most `points` values, oldest to newest."""
    closes = df["close"].dropna()
    if closes.empty:
        return []
    if len(closes) <= points:
        sampled = closes
    else:
        idx = np.linspace(0, len(closes) - 1, points).round().astype(int)
        sampled = closes.iloc[idx]
    return [float(v) for v in sampled]
