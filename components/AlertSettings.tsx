"use client";

import { useState } from "react";
import type { AlertMode } from "@/lib/types";

const OPTIONS: { value: AlertMode; label: string }[] = [
  { value: "crypto", label: "คริปโตเท่านั้น" },
  { value: "stock", label: "หุ้นเท่านั้น" },
  { value: "both", label: "ทั้งสองอย่าง" },
  { value: "none", label: "ปิดการแจ้งเตือน" },
];

export function AlertSettings({ initialMode }: { initialMode: AlertMode }) {
  const [mode, setMode] = useState(initialMode);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = async (next: AlertMode) => {
    if (next === mode || saving) return;
    const prev = mode;
    setMode(next);
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/alert-settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ alert_mode: next }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${res.status}`);
      }
    } catch (err) {
      setMode(prev);
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="alert-settings">
      <span className="alert-settings-label">แจ้งเตือน Telegram:</span>
      <div className="alert-settings-options" role="radiogroup" aria-label="เลือกประเภทการแจ้งเตือน">
        {OPTIONS.map((opt) => (
          <label key={opt.value} className={`alert-option ${mode === opt.value ? "active" : ""}`}>
            <input
              type="radio"
              name="alert_mode"
              value={opt.value}
              checked={mode === opt.value}
              disabled={saving}
              onChange={() => handleChange(opt.value)}
            />
            {opt.label}
          </label>
        ))}
      </div>
      {saving && <span className="alert-settings-status">กำลังบันทึก...</span>}
      {error && <span className="alert-settings-status error">บันทึกไม่สำเร็จ: {error}</span>}
    </div>
  );
}
