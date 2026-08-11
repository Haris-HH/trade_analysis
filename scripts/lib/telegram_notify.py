"""Send alert messages via the Telegram Bot API."""
from __future__ import annotations

import os
import requests

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _fmt_price(value: float) -> str:
    decimals = 4 if value < 10 else 2
    return f"{value:,.{decimals}f}"


def send_telegram_message(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, skipping send")
        return False

    resp = requests.post(
        TELEGRAM_API.format(token=token),
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=15,
    )
    if not resp.ok:
        print(f"[telegram] send failed: {resp.status_code} {resp.text}")
        return False
    return True


def format_signal_message(signal: dict) -> str:
    emoji = "🟢" if signal["direction"] == "BUY" else "🔴"
    market_th = "คริปโต" if signal["market"] == "crypto" else "หุ้น"
    action_th = "ซื้อทันที (BUY NOW)" if signal["direction"] == "BUY" else "ขายทันที (SELL NOW)"

    lines = [
        f"{emoji} <b>แนะนำ: {action_th}</b>",
        f"{signal['symbol']} ({market_th}) — {signal['display_name']}",
        f"ความมั่นใจ: <b>{signal['confidence']:.0f}%</b> (เทคนิค {signal['technical_score']:.0f} / ข่าว {signal['news_score']:.0f}, "
        f"ปัจจัยเห็นตรงกัน {signal['agreement']:.0%}) — ตรวจสอบซ้ำแล้ว ✓",
        f"ราคาปัจจุบัน: {_fmt_price(signal['price'])}",
    ]

    target = signal.get("price_target")
    if target:
        lines.append(
            f"เป้าหมาย (ประมาณการ): {_fmt_price(target['target_price'])} ภายในวันที่ {target['target_date']} "
            f"(~{target['horizon_days']:g} วัน)"
        )

    lines += ["", "เหตุผล:"]
    lines += [f"• {r}" for r in signal["reasons"]]
    lines.append("")
    if target:
        lines.append(
            "⚠️ เป้าหมายราคาเป็นการประมาณจากความผันผวนล่าสุด (measured move) ไม่ใช่การพยากรณ์ทางสถิติ "
            "และไม่ใช่การรับประกันว่าราคาจะไปถึงจริง"
        )
    lines.append("⚠️ นี่ไม่ใช่คำแนะนำการลงทุนจากผู้เชี่ยวชาญที่ได้รับใบอนุญาต เป็นสัญญาณอัตโนมัติเพื่อการศึกษาเท่านั้น โปรดตรวจสอบข้อมูลเพิ่มเติมก่อนตัดสินใจลงทุนจริง")
    return "\n".join(lines)
