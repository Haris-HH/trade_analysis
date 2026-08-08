"""Send alert messages via the Telegram Bot API."""
from __future__ import annotations

import os
import requests

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


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
    lines = [
        f"{emoji} <b>{signal['direction']} {signal['symbol']}</b> ({market_th})",
        f"ความมั่นใจ: <b>{signal['confidence']:.0f}%</b> (เทคนิค {signal['technical_score']:.0f} / ข่าว {signal['news_score']:.0f})",
        f"ราคาปัจจุบัน: {signal['price']}",
        "",
        "เหตุผล:",
    ]
    lines += [f"• {r}" for r in signal["reasons"]]
    lines.append("")
    lines.append("⚠️ นี่ไม่ใช่คำแนะนำการลงทุน เป็นสัญญาณอัตโนมัติเพื่อการศึกษาเท่านั้น โปรดตรวจสอบข้อมูลเพิ่มเติมก่อนตัดสินใจ")
    return "\n".join(lines)
