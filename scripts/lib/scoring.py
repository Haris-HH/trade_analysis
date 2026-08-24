"""Confluence scoring engine — ported from QuantDesk's approach
(D:\\Haris\\Quantdesk\\core\\signals.py): weighted factor voting +
agreement-adjusted confidence + veto rules, instead of a flat weighted sum
of a single technical number and a single news number.

Each factor votes in [-1, +1] with a fixed weight. Direction comes from the
weighted-average sign; confidence blends |score| with how much of the total
weight agrees with that sign — a score of +0.6 from five agreeing factors
means more than +0.6 from one loud factor and four silent ones — and is
capped at 90: never claim near-certainty. A signal that clears the
confidence bar can still be vetoed: no valid stop/target, poor
risk:reward, or insufficient factor agreement.

`trend_confluence`, `smart_money`, and `volume_profile` (see
lib/indicators.py) are heuristic approximations of three TradingView tools
the user trades alongside this engine — justUncle's "Big Snapper" alert
(fast/medium MA cross confirmed by a SuperTrend flip), chartPrime's "Smart
Money Breakouts" + MyTradingCoder's magnified order block (break of
structure + order block pullback), and a classic volume-profile POC/value
area read — folded in as extra votes rather than as separate chart overlays,
since this engine has no chart to draw on.
"""
from __future__ import annotations

from dataclasses import dataclass

# Same weights QuantDesk uses as a base; "trend" still carries the most
# weight of any single factor, but "trend_confluence" + "smart_money" add
# two more trend/structure-confirming votes on top of it (see module
# docstring), so the combined trend-family weight is actually higher than
# before. "news" stays low because it's the noisiest and most often absent.
WEIGHTS = {
    "trend": 0.18,
    "momentum": 0.13,
    "macd": 0.12,
    "mean_reversion": 0.08,
    "volume": 0.06,
    "volume_profile": 0.08,
    "smart_money": 0.14,
    "trend_confluence": 0.11,
    "news": 0.10,
}

CONFIDENCE_CAP = 90.0
MIN_AGREEMENT = 0.6
MIN_RR = 1.5
ATR_STOP_MULTIPLE = 1.5
ATR_TARGET_MULTIPLE = 2.5


@dataclass(slots=True)
class Factor:
    name: str
    vote: float  # -1..+1
    weight: float
    detail: str

    @property
    def contribution(self) -> float:
        return self.vote * self.weight


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def aggregate(factors: list[Factor]) -> dict:
    """Combine factor votes into score/confidence/agreement/direction."""
    total_weight = sum(f.weight for f in factors)
    if total_weight == 0:
        return {"score": 0.0, "confidence": 0.0, "agreement": 0.0, "direction": "BUY", "coverage": 0.0}

    score = sum(f.contribution for f in factors) / total_weight

    if score != 0:
        agree_w = sum(f.weight for f in factors if f.vote != 0 and (f.vote > 0) == (score > 0))
        voting_w = sum(f.weight for f in factors if f.vote != 0)
        agreement = agree_w / voting_w if voting_w else 0.0
    else:
        agreement = 0.0

    raw_conf = (abs(score) ** 0.65) * 100 * (0.55 + 0.45 * agreement)
    coverage = total_weight / sum(WEIGHTS.values())
    confidence = min(CONFIDENCE_CAP, raw_conf * coverage)

    return {
        "score": score,
        "confidence": confidence,
        "agreement": agreement,
        "direction": "BUY" if score >= 0 else "SELL",
        "coverage": coverage,
    }


def best_case_confidence(tech_factors: list[Factor]) -> float:
    """Highest confidence achievable if news voted maximally in the technical
    read's favor. Used to skip news lookups that mathematically can't matter —
    keeps a ~950-symbol scan from hitting news APIs 950 times per run."""
    if not tech_factors:
        return 0.0
    tech_only = aggregate(tech_factors)
    hypothetical_news = Factor("news", 1.0 if tech_only["score"] >= 0 else -1.0, WEIGHTS["news"], "hypothetical")
    return aggregate(tech_factors + [hypothetical_news])["confidence"]


def compute_stop_target(direction: str, price: float, atr: float | None) -> dict | None:
    """ATR-scaled stop/target for the risk:reward veto check (not the
    longer-horizon measured-move target shown on the dashboard — see
    price_target.py for that)."""
    if atr is None or atr <= 0:
        return None
    if direction == "BUY":
        stop = price - ATR_STOP_MULTIPLE * atr
        target = price + ATR_TARGET_MULTIPLE * atr
    else:
        stop = price + ATR_STOP_MULTIPLE * atr
        target = price - ATR_TARGET_MULTIPLE * atr
    risk = abs(price - stop)
    reward = abs(target - price)
    rr = (reward / risk) if risk > 0 else None
    return {"stop": stop, "target": target, "rr": rr}


def check_veto(*, agreement: float, rr: float | None) -> str | None:
    """Returns a veto reason, or None if the signal survives. A signal that
    clears the confidence bar can still be vetoed here — confidence measures
    factor agreement, not whether the trade is actually worth taking."""
    if rr is None:
        return "Veto: คำนวณ stop/target ไม่ได้ (ATR ใช้ไม่ได้)"
    if rr < MIN_RR:
        return f"Veto: Risk:Reward {rr:.2f} ต่ำกว่าเกณฑ์ {MIN_RR:g}"
    if agreement < MIN_AGREEMENT:
        return f"Veto: ปัจจัยเห็นตรงกันแค่ {agreement:.0%} (ต้อง ≥{MIN_AGREEMENT:.0%})"
    return None
