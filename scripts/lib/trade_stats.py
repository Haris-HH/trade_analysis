"""Portfolio performance analytics computed from data/trade_log.json,
mirroring the win-rate/profit-factor/R-multiple/max-drawdown formulas in
the account's own ORC_CRYPTO Position Sizer trade journal
(ORC_CRYPTO_PositionSizer_FREE_V4.html, see also the "Position sizing"
video at youtube.com/watch?v=c6DFdPf5bug) — so the bot's own auto-trade
notifications carry the same "how am I actually doing" numbers the manual
tool computes, not just each individual trade's P&L.

R-multiple here is approximated as pnl_pct / STOP_LOSS_PCT (the auto-trader
uses a fixed stop-loss percentage, not a per-trade dollar risk amount
recorded on the trade log), which is a reasonable stand-in for "how many
multiples of planned risk did this trade return" without needing to widen
the trade log schema.
"""
from __future__ import annotations


def compute_stats(trade_log: list[dict], stop_loss_pct: float) -> dict:
    """stop_loss_pct: auto_trader.STOP_LOSS_PCT (e.g. 0.08), used only for
    the R-multiple approximation. Pass 0 (or the SL is disabled) to skip it."""
    sells = [t for t in trade_log if t.get("side") == "sell" and isinstance(t.get("pnl_thb"), (int, float))]
    if not sells:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": None, "profit_factor": None, "avg_r": None,
            "total_pnl_thb": 0.0, "max_drawdown_thb": None,
        }

    wins = [t for t in sells if t["pnl_thb"] > 0]
    losses = [t for t in sells if t["pnl_thb"] <= 0]
    sum_win = sum(t["pnl_thb"] for t in wins)
    sum_loss = sum(-t["pnl_thb"] for t in losses)
    total_pnl = sum(t["pnl_thb"] for t in sells)

    r_values = [
        t["pnl_pct"] / stop_loss_pct for t in sells
        if isinstance(t.get("pnl_pct"), (int, float)) and stop_loss_pct > 0
    ]
    avg_r = (sum(r_values) / len(r_values)) if r_values else None

    running, peak, max_dd = 0.0, 0.0, 0.0
    for t in sells:  # trade_log is append-only -> already chronological
        running += t["pnl_thb"]
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)

    return {
        "total_trades": len(sells),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(sells)) * 100,
        "profit_factor": (sum_win / sum_loss) if sum_loss > 0 else (float("inf") if sum_win > 0 else None),
        "avg_r": avg_r,
        "total_pnl_thb": total_pnl,
        "max_drawdown_thb": max_dd,
    }


def format_summary_th(stats: dict) -> str:
    if stats["total_trades"] == 0:
        return "ยังไม่มีเทรดที่ปิดสมบูรณ์ (ไม่มีข้อมูลสถิติ)"

    pf = stats["profit_factor"]
    pf_str = "∞" if pf == float("inf") else (f"{pf:.2f}" if pf is not None else "—")
    r_str = f"{stats['avg_r']:+.2f}R" if stats["avg_r"] is not None else "—"

    return (
        f"เทรดปิดแล้ว {stats['total_trades']} ครั้ง ({stats['wins']}W/{stats['losses']}L) "
        f"— Win Rate {stats['win_rate']:.1f}%\n"
        f"Profit Factor {pf_str} | ค่าเฉลี่ย {r_str}\n"
        f"กำไร/ขาดทุนสะสม: {stats['total_pnl_thb']:+,.2f} THB | "
        f"Max Drawdown: -{stats['max_drawdown_thb']:,.2f} THB"
    )
