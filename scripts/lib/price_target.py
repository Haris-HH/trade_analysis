"""Heuristic price target + target date estimation.

This is a technical-analysis heuristic, NOT a statistical forecast:

  1. Target distance = ATR_MULTIPLIER x Average True Range(14) — a common
     "measured move" projection technique (project a multiple of recent
     volatility from the current price in the signal's direction).
  2. Time-to-target = target distance / the recent average per-bar price
     move, converted to a calendar date using the chart's own bar interval
     (so it works whether the underlying bars are hourly crypto candles or
     15-minute/daily stock bars).

Actual price paths are highly uncertain — this estimates "if the market kept
moving at its recent pace," nothing more. Every caller must surface that
caveat alongside the number.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import ta

ATR_MULTIPLIER = 15.0
MAX_HORIZON_DAYS = 90
MIN_BARS = 20

# Stocks only trade ~6.5h/day, so an intraday bar count needs converting to
# calendar time via trading hours, then padded for weekends — otherwise a
# target "reachable in 5 trading hours" would misleadingly show as "today"
# even when markets are closed for most of the next 24 hours.
US_TRADING_HOURS_PER_DAY = 6.5
TRADING_TO_CALENDAR_DAY_RATIO = 7 / 5


def estimate_price_target(
    df: pd.DataFrame, direction: str, current_price: float, market: str = "crypto"
) -> dict | None:
    if len(df) < MIN_BARS:
        return None

    atr_series = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range()
    atr = float(atr_series.iloc[-1])
    if not atr or np.isnan(atr) or atr <= 0:
        return None

    target_distance = ATR_MULTIPLIER * atr
    target_price = current_price + target_distance if direction == "BUY" else current_price - target_distance
    if target_price <= 0:
        return None

    avg_move_per_bar = float(df["close"].diff().abs().tail(20).mean())
    if not avg_move_per_bar or np.isnan(avg_move_per_bar) or avg_move_per_bar <= 0:
        return None

    bars_to_target = target_distance / avg_move_per_bar
    bar_interval = df.index[-1] - df.index[-2]
    bar_minutes = bar_interval.total_seconds() / 60
    if bar_minutes <= 0:
        return None

    is_intraday_stock_bar = market == "stock" and bar_minutes < 60 * 20
    if is_intraday_stock_bar:
        total_minutes = bars_to_target * bar_minutes
        trading_days = total_minutes / (US_TRADING_HOURS_PER_DAY * 60)
        horizon_days = trading_days * TRADING_TO_CALENDAR_DAY_RATIO
    else:
        horizon_days = (bar_interval * bars_to_target).total_seconds() / 86400

    if horizon_days <= 0 or horizon_days > MAX_HORIZON_DAYS:
        return None

    target_date = (df.index[-1].to_pydatetime() + timedelta(days=horizon_days)).date().isoformat()

    return {
        "target_price": round(target_price, 8),
        "target_date": target_date,
        "horizon_days": round(horizon_days, 1),
        "method": f"measured move: {ATR_MULTIPLIER:g}x ATR(14) projected at recent momentum pace",
    }
