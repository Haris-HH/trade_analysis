"""Technical indicator scoring.

Turns a price/volume dataframe into a signed score in [-100, 100]:
positive = bullish (BUY lean), negative = bearish (SELL lean).
Each indicator "votes" and the votes are combined with fixed weights.
This is a simple heuristic system, not a proven trading strategy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import ta


def compute_technical_score(df: pd.DataFrame) -> tuple[float, list[str]]:
    """df must have columns: close, high, low, volume, indexed by time, ascending."""
    reasons: list[str] = []
    if len(df) < 35:
        return 0.0, ["ข้อมูลราคาไม่พอสำหรับคำนวณอินดิเคเตอร์"]

    close = df["close"]
    votes = 0.0
    max_votes = 0.0

    # RSI(14): oversold -> bullish, overbought -> bearish
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
    last_rsi = float(rsi.iloc[-1])
    max_votes += 25
    if last_rsi <= 30:
        votes += 25
        reasons.append(f"RSI oversold ({last_rsi:.1f}) → bullish")
    elif last_rsi >= 70:
        votes -= 25
        reasons.append(f"RSI overbought ({last_rsi:.1f}) → bearish")
    elif last_rsi < 45:
        votes += 8
    elif last_rsi > 55:
        votes -= 8

    # MACD cross
    macd_ind = ta.trend.MACD(close)
    macd_line = macd_ind.macd()
    signal_line = macd_ind.macd_signal()
    max_votes += 30
    if len(macd_line) >= 2:
        prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
        cur_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
        if prev_diff <= 0 < cur_diff:
            votes += 30
            reasons.append("MACD bullish crossover")
        elif prev_diff >= 0 > cur_diff:
            votes -= 30
            reasons.append("MACD bearish crossover")
        elif cur_diff > 0:
            votes += 10
        elif cur_diff < 0:
            votes -= 10

    # EMA20 vs EMA50 trend
    ema20 = ta.trend.EMAIndicator(close, window=20).ema_indicator()
    ema50 = ta.trend.EMAIndicator(close, window=50).ema_indicator() if len(close) >= 50 else None
    max_votes += 20
    if ema50 is not None and not np.isnan(ema50.iloc[-1]):
        if ema20.iloc[-1] > ema50.iloc[-1]:
            votes += 20
            reasons.append("EMA20 > EMA50 (แนวโน้มขาขึ้น)")
        else:
            votes -= 20
            reasons.append("EMA20 < EMA50 (แนวโน้มขาลง)")

    # Bollinger %B
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    pct_b = bb.bollinger_pband()
    max_votes += 15
    last_pb = float(pct_b.iloc[-1]) if not np.isnan(pct_b.iloc[-1]) else 0.5
    if last_pb <= 0.05:
        votes += 15
        reasons.append("ราคาแตะขอบล่าง Bollinger Band → bullish")
    elif last_pb >= 0.95:
        votes -= 15
        reasons.append("ราคาแตะขอบบน Bollinger Band → bearish")

    # Volume spike confirms the move direction
    if "volume" in df.columns and df["volume"].iloc[-20:].mean() > 0:
        avg_vol = df["volume"].iloc[-20:-1].mean()
        last_vol = df["volume"].iloc[-1]
        max_votes += 10
        if avg_vol > 0 and last_vol > 1.5 * avg_vol:
            price_change = close.iloc[-1] - close.iloc[-2]
            if price_change > 0:
                votes += 10
                reasons.append("ปริมาณซื้อขายพุ่งพร้อมราคาขึ้น")
            elif price_change < 0:
                votes -= 10
                reasons.append("ปริมาณซื้อขายพุ่งพร้อมราคาลง")

    score = 100.0 * votes / max_votes if max_votes else 0.0
    score = max(-100.0, min(100.0, score))
    return score, reasons
