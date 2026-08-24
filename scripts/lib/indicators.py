"""Regime-aware technical factor scoring — ported from QuantDesk's engine
(D:\\Haris\\Quantdesk\\core\\signals.py / indicators.py).

The key idea: RSI and Bollinger %B are mean-reversion tools. They're correct
in a ranging market and actively harmful in a trending one — RSI sits above
70 for the entire length of a real rally, so reading it as "overbought"
there means fighting every trend the market gives you. This module detects
the regime first (from EMA20/EMA50 separation) and flips how those two
factors are interpreted accordingly.

Below MIN_CANDLES, compute_factors() returns an empty list rather than a
plausible-looking number computed from insufficient warmup data — the
caller treats that as "no opinion" (QuantDesk's ABSTAIN), not as a weak BUY.

Three factors here are heuristic ports of TradingView indicators, since a
Python engine has no chart to attach a Pine Script overlay to:
- `_compute_trend_confluence` — approximates justUncle's "Big Snapper"
  alert: a fast/medium EMA cross that only counts fully when a SuperTrend
  flip agrees with it, the same multi-confirmation idea behind Big Snapper's
  buy/sell arrows once its raw MA/BB overlay plots are unchecked.
- `_compute_smart_money` — approximates chartPrime's "Smart Money
  Breakouts" + MyTradingCoder's magnified order block: break-of-structure
  (price closing beyond the last confirmed swing high/low) plus the order
  block zone (last opposite-colored candle before the breakout leg) for a
  higher-quality pullback entry.
- `_compute_volume_profile` — a POC/value-area read (point of control +
  70%-of-volume value area over the recent lookback), voting on whether
  price is breaking out of, or drifting back toward, the high-volume node.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import ta

from .scoring import Factor, WEIGHTS

MIN_CANDLES = 60
TREND_THRESHOLD = 0.008  # 0.8% EMA20/EMA50 separation marks a trending regime


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def compute_factors(df: pd.DataFrame) -> list[Factor]:
    """df: columns open/high/low/close/volume, ascending time index."""
    if len(df) < MIN_CANDLES:
        return []

    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
    price = float(close.iloc[-1])
    factors: list[Factor] = []
    trending = False

    # ---- Regime detection (must run before RSI/Bollinger) ----
    ema20_series = ta.trend.EMAIndicator(close, window=20).ema_indicator()
    ema50_series = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    ema20, ema50 = float(ema20_series.iloc[-1]), float(ema50_series.iloc[-1])
    if pd.notna(ema20) and pd.notna(ema50) and ema50 != 0:
        trend_strength = abs((ema20 - ema50) / ema50)
        trending = trend_strength > TREND_THRESHOLD
        regime = "เทรนด์" if trending else "ไซด์เวย์"

        sep = (ema20 - ema50) / ema50
        vote = _clamp(sep * 40)  # ~2.5% separation saturates the vote
        above = price > ema20
        if (vote > 0) != above:
            vote *= 0.4  # price on the wrong side of the fast EMA weakens the read
        factors.append(Factor(
            "trend", vote, WEIGHTS["trend"],
            f"EMA20 {ema20:,.4g} vs EMA50 {ema50:,.4g} ({sep:+.2%}); "
            f"ราคาอยู่{'เหนือ' if above else 'ใต้'} EMA20 [{regime}]",
        ))

    # ---- Momentum: RSI, regime-aware ----
    rsi_series = ta.momentum.RSIIndicator(close, window=14).rsi()
    if pd.notna(rsi_series.iloc[-1]):
        r = float(rsi_series.iloc[-1])
        if trending:
            # In a trend, RSI measures strength, not exhaustion. Only a
            # genuine extreme counts as a warning sign.
            if r >= 80:
                vote, desc = -0.3, f"RSI {r:.1f} overbought สุดขั้วแม้อยู่ในเทรนด์"
            elif r <= 20:
                vote, desc = 0.3, f"RSI {r:.1f} oversold สุดขั้วแม้อยู่ในเทรนด์"
            else:
                vote, desc = _clamp((r - 50) / 30), f"RSI {r:.1f} ยืนยันความแข็งแรงของเทรนด์"
        else:
            if r >= 70:
                vote, desc = -_clamp((r - 70) / 20), f"RSI {r:.1f} overbought ในไซด์เวย์"
            elif r <= 30:
                vote, desc = _clamp((30 - r) / 20), f"RSI {r:.1f} oversold ในไซด์เวย์"
            else:
                vote, desc = (r - 50) / 40, f"RSI {r:.1f} โซนกลาง"
        factors.append(Factor("momentum", _clamp(vote), WEIGHTS["momentum"], desc))

    # ---- MACD: histogram direction + expansion ----
    macd_ind = ta.trend.MACD(close)
    macd_line = macd_ind.macd()
    signal_line = macd_ind.macd_signal()
    hist = macd_line - signal_line
    if len(hist) >= 2 and pd.notna(hist.iloc[-1]) and pd.notna(hist.iloc[-2]):
        cur_hist, prev_hist = float(hist.iloc[-1]), float(hist.iloc[-2])
        cross = macd_line.iloc[-1] > signal_line.iloc[-1]
        vote = 0.5 if cross else -0.5
        expanding = abs(cur_hist) > abs(prev_hist)
        if expanding:
            vote *= 1.6
        flipped = (cur_hist > 0) != (prev_hist > 0)
        if flipped:
            vote = 0.9 if cur_hist > 0 else -0.9
        factors.append(Factor(
            "macd", _clamp(vote), WEIGHTS["macd"],
            f"MACD hist {cur_hist:+.4g}"
            f"{' (ขยายตัว)' if expanding else ''}{' (เพิ่งกลับทิศ)' if flipped else ''}",
        ))

    # ---- Bollinger %B: fade in a range, confirm in a trend ----
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    pct_b_series = bb.bollinger_pband()
    if pd.notna(pct_b_series.iloc[-1]):
        pct_b = float(pct_b_series.iloc[-1])
        upper, lower, mid = (
            float(bb.bollinger_hband().iloc[-1]),
            float(bb.bollinger_lband().iloc[-1]),
            float(bb.bollinger_mavg().iloc[-1]),
        )
        width = (upper - lower) / mid if mid else 0.0
        if trending:
            vote = _clamp((pct_b - 0.5) * 1.2)
            mode = "ขี่แถบยืนยันเทรนด์"
        else:
            vote = _clamp((0.5 - pct_b) * 2.0)
            mode = "fade ที่จุดสุดขั้วในไซด์เวย์"
        squeeze = width < 0.02
        if squeeze:
            vote *= 0.3
        factors.append(Factor(
            "mean_reversion", vote, WEIGHTS["mean_reversion"],
            f"%B={pct_b:.2f}, width={width:.2%} [{mode}]"
            + (" ⚠ Bollinger squeeze — ทิศทางไม่แน่นอน" if squeeze else ""),
        ))

    # ---- Volume: amplifies the existing read, never originates one ----
    if len(volume) >= 21:
        avg_vol = float(volume.iloc[-21:-1].mean())
        if avg_vol > 0:
            vr = float(volume.iloc[-1]) / avg_vol
            prior = sum(f.contribution for f in factors)
            vote = _clamp(vr - 1.0) * (1.0 if prior >= 0 else -1.0)
            factors.append(Factor(
                "volume", vote, WEIGHTS["volume"],
                f"ปริมาณซื้อขาย {vr:.2f} เท่าของค่าเฉลี่ย 20 แท่ง" + (" (สูงผิดปกติ)" if vr > 1.5 else ""),
            ))

    # ---- Big Snapper-style confluence: fast/medium MA cross + SuperTrend ----
    try:
        confluence = _compute_trend_confluence(df)
        if confluence:
            factors.append(confluence)
    except Exception:
        pass

    # ---- Smart money structure: break of structure + order block ----
    try:
        smart_money = _compute_smart_money(df)
        if smart_money:
            factors.append(smart_money)
    except Exception:
        pass

    # ---- Volume profile: point of control / value area ----
    try:
        vol_profile = _compute_volume_profile(df)
        if vol_profile:
            factors.append(vol_profile)
    except Exception:
        pass

    return factors


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    """Classic SuperTrend: ATR-scaled trailing bands that flip trend
    direction when price closes through the opposite band. Returns
    (uptrend, line_price, just_flipped) or (None, None, False) if there
    isn't enough warmup data."""
    n = len(df)
    if n < period + 5:
        return None, None, False

    high, low, close = df["high"].values, df["low"].values, df["close"].values
    atr = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=period).average_true_range().values
    valid = np.where(~np.isnan(atr))[0]
    if len(valid) == 0:
        return None, None, False
    start = int(valid[0])

    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    trend = np.zeros(n, dtype=bool)  # True = uptrend

    final_upper[start] = basic_upper[start]
    final_lower[start] = basic_lower[start]
    trend[start] = True

    for i in range(start + 1, n):
        if np.isnan(atr[i]):
            final_upper[i], final_lower[i], trend[i] = final_upper[i - 1], final_lower[i - 1], trend[i - 1]
            continue
        final_upper[i] = basic_upper[i] if (basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]) else final_upper[i - 1]
        final_lower[i] = basic_lower[i] if (basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]) else final_lower[i - 1]
        if trend[i - 1] and close[i] < final_lower[i]:
            trend[i] = False
        elif not trend[i - 1] and close[i] > final_upper[i]:
            trend[i] = True
        else:
            trend[i] = trend[i - 1]

    uptrend = bool(trend[-1])
    line = float(final_lower[-1] if uptrend else final_upper[-1])
    lookback = min(3, n - start - 1)
    just_flipped = lookback > 0 and bool(np.any(trend[-lookback - 1:-1] != uptrend))
    return uptrend, line, just_flipped


def _compute_trend_confluence(df: pd.DataFrame) -> Factor | None:
    close = df["close"]
    if len(close) < 55:
        return None
    uptrend, line, just_flipped = _supertrend(df)
    if uptrend is None:
        return None

    fast = close.ewm(span=8, adjust=False).mean()
    medium = close.ewm(span=21, adjust=False).mean()
    fast_v, med_v = float(fast.iloc[-1]), float(medium.iloc[-1])
    prev_fast, prev_med = float(fast.iloc[-2]), float(medium.iloc[-2])
    ma_bull = fast_v > med_v
    cross_now = (prev_fast <= prev_med) != (fast_v <= med_v)
    agrees = ma_bull == uptrend

    vote = (0.5 if ma_bull else -0.5) * (1.6 if agrees else 0.6)
    if cross_now and agrees:
        vote = 1.0 if ma_bull else -1.0

    desc = (
        f"Fast/Medium MA {'ตัดขึ้น' if ma_bull else 'ตัดลง'}"
        f"{' + SuperTrend ยืนยัน (เส้น ' + f'{line:,.4g})' if agrees else ' แต่ SuperTrend ยังไม่ยืนยัน'}"
        f"{' — สัญญาณใหม่ล่าสุด แบบ Big Snapper' if cross_now and agrees else ''}"
    )
    return Factor("trend_confluence", _clamp(vote), WEIGHTS["trend_confluence"], desc)


def _find_swings(high: np.ndarray, low: np.ndarray, lookback: int = 60, arm: int = 2):
    n = len(high)
    start = max(arm, n - lookback)
    swing_highs, swing_lows = [], []
    for i in range(start, n - arm):
        wh, wl = high[i - arm:i + arm + 1], low[i - arm:i + arm + 1]
        if high[i] == wh.max() and np.sum(wh == high[i]) == 1:
            swing_highs.append((i, high[i]))
        if low[i] == wl.min() and np.sum(wl == low[i]) == 1:
            swing_lows.append((i, low[i]))
    return swing_highs, swing_lows


def _compute_smart_money(df: pd.DataFrame) -> Factor | None:
    if len(df) < 30:
        return None
    high, low, close, open_ = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    n = len(close)
    swing_highs, swing_lows = _find_swings(high, low, lookback=60, arm=2)
    if not swing_highs or not swing_lows:
        return None

    last_high_idx, last_high = swing_highs[-1]
    last_low_idx, last_low = swing_lows[-1]
    price = float(close[-1])
    FRESH_BARS = 6

    def _recent_break(level_idx: int, level: float, above: bool) -> int | None:
        for i in range(level_idx + 1, n):
            if (close[i] > level) if above else (close[i] < level):
                return i
        return None

    up_break_idx = _recent_break(last_high_idx, last_high, True)
    down_break_idx = _recent_break(last_low_idx, last_low, False)

    if up_break_idx is not None and (down_break_idx is None or up_break_idx >= down_break_idx):
        fresh = (n - 1 - up_break_idx) <= FRESH_BARS
        vote = 0.9 if fresh else 0.4
        ob_idx = next((i for i in range(up_break_idx, last_high_idx, -1) if close[i] < open_[i]), None)
        in_ob = False
        if ob_idx is not None:
            ob_low, ob_high = min(low[ob_idx], close[ob_idx]), max(open_[ob_idx], high[ob_idx])
            in_ob = ob_low <= price <= ob_high
            if in_ob:
                vote = min(1.0, vote + 0.3)
        desc = (
            f"Break of Structure ขาขึ้น เหนือ {last_high:,.4g}{' (สดใหม่)' if fresh else ''}"
            + (" + ราคาย่อกลับเข้า Order Block ขาขึ้น" if in_ob else "")
        )
        return Factor("smart_money", _clamp(vote), WEIGHTS["smart_money"], desc)

    if down_break_idx is not None:
        fresh = (n - 1 - down_break_idx) <= FRESH_BARS
        vote = -0.9 if fresh else -0.4
        ob_idx = next((i for i in range(down_break_idx, last_low_idx, -1) if close[i] > open_[i]), None)
        in_ob = False
        if ob_idx is not None:
            ob_low, ob_high = min(open_[ob_idx], low[ob_idx]), max(high[ob_idx], close[ob_idx])
            in_ob = ob_low <= price <= ob_high
            if in_ob:
                vote = max(-1.0, vote - 0.3)
        desc = (
            f"Break of Structure ขาลง ใต้ {last_low:,.4g}{' (สดใหม่)' if fresh else ''}"
            + (" + ราคาเด้งกลับเข้า Order Block ขาลง" if in_ob else "")
        )
        return Factor("smart_money", _clamp(vote), WEIGHTS["smart_money"], desc)

    return None


def _compute_volume_profile(df: pd.DataFrame, bins: int = 20, lookback: int = 100) -> Factor | None:
    n = len(df)
    if n < 30:
        return None
    sub = df.iloc[max(0, n - lookback):]
    lo, hi = float(sub["low"].min()), float(sub["high"].max())
    if hi <= lo:
        return None

    edges = np.linspace(lo, hi, bins + 1)
    typical = ((sub["high"] + sub["low"] + sub["close"]) / 3.0).values
    vols = sub["volume"].values
    bin_idx = np.clip(np.digitize(typical, edges) - 1, 0, bins - 1)
    vol_by_bin = np.zeros(bins)
    np.add.at(vol_by_bin, bin_idx, vols)
    total_vol = vol_by_bin.sum()
    if total_vol <= 0:
        return None

    poc_bin = int(vol_by_bin.argmax())
    poc_price = (edges[poc_bin] + edges[poc_bin + 1]) / 2.0

    order = np.argsort(-vol_by_bin)
    included, cum = [], 0.0
    for i in order:
        included.append(int(i))
        cum += vol_by_bin[i]
        if cum >= 0.7 * total_vol:
            break
    val_price = float(edges[min(included)])
    vah_price = float(edges[max(included) + 1])

    price = float(df["close"].iloc[-1])
    va_width = max(vah_price - val_price, (hi - lo) * 0.01)

    if price > vah_price:
        vote = _clamp(0.5 + (price - vah_price) / va_width)
        desc = f"ราคาหลุดเหนือ Value Area (POC {poc_price:,.4g}) — breakout เหนือโซนแออัดของปริมาณซื้อขาย"
    elif price < val_price:
        vote = _clamp(-0.5 - (val_price - price) / va_width)
        desc = f"ราคาหลุดใต้ Value Area (POC {poc_price:,.4g}) — breakdown ใต้โซนแออัดของปริมาณซื้อขาย"
    else:
        vote = _clamp((poc_price - price) / va_width * 0.5)
        desc = f"ราคาอยู่ใน Value Area (POC {poc_price:,.4g}) — โน้มเข้าหาโซนปริมาณซื้อขายหนาแน่น"

    return Factor("volume_profile", vote, WEIGHTS["volume_profile"], desc)


def compute_atr(df: pd.DataFrame, window: int = 14) -> float | None:
    if len(df) < window + 1:
        return None
    atr_series = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=window).average_true_range()
    val = float(atr_series.iloc[-1])
    return val if val > 0 and not np.isnan(val) else None
