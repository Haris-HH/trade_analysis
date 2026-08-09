import fs from "fs";
import path from "path";
import type { AnalysisData } from "@/lib/types";
import { Sparkline } from "@/components/Sparkline";

export const revalidate = 0;

function loadData(): AnalysisData {
  const file = path.join(process.cwd(), "public", "data", "latest.json");
  const raw = fs.readFileSync(file, "utf-8");
  return JSON.parse(raw);
}

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  return `${hrs} hr ago`;
}

export default function Home() {
  const data = loadData();
  const signals = [...data.signals].sort((a, b) => b.confidence - a.confidence);

  return (
    <main className="container">
      <header className="hero">
        <h1>📊 Trade Signal Dashboard</h1>
        <p>Technical indicators + news sentiment scanner for crypto &amp; stocks</p>
      </header>

      <div className="disclaimer">
        <strong>ไม่ใช่คำแนะนำการลงทุน</strong> — เว็บนี้เป็นเครื่องมือให้ข้อมูลเชิงสถิติ/สัญญาณอัตโนมัติ
        เพื่อการศึกษาเท่านั้น ไม่ได้รับใบอนุญาตเป็นที่ปรึกษาการลงทุน คะแนนความมั่นใจเป็นค่าประมาณจากอินดิเคเตอร์ทางเทคนิคและ
        การวิเคราะห์ความรู้สึกของข่าวเท่านั้น ไม่ใช่การรับประกันผลลัพธ์ โปรดตัดสินใจลงทุนด้วยวิจารณญาณของคุณเองและศึกษาข้อมูลเพิ่มเติมก่อนเสมอ
        <br />
        {data.disclaimer}
      </div>

      <div className="meta-row">
        <span className="badge">อัปเดตล่าสุด: {timeAgo(data.generated_at)}</span>
        <span className="badge">เกณฑ์แจ้งเตือน: ≥ {data.min_confidence_threshold}%</span>
        <span className="badge">คริปโตที่สแกน: {data.watchlist_counts.crypto}</span>
        <span className="badge">หุ้นที่สแกน: {data.watchlist_counts.stock}</span>
      </div>

      {signals.length === 0 ? (
        <div className="empty-state">ยังไม่มีข้อมูล รอรอบสแกนถัดไป...</div>
      ) : (
        <div className="grid">
          {signals.map((s) => (
            <div className="card" key={`${s.market}-${s.symbol}`}>
              <div className="card-head">
                <div>
                  <div className="symbol">{s.symbol}</div>
                  <div className="name">
                    {s.display_name} · {s.market === "crypto" ? "คริปโต" : "หุ้น"}
                  </div>
                </div>
                <span className={`direction ${s.direction}`}>{s.direction}</span>
              </div>

              <div className="confidence-row">
                <div className="confidence-bar">
                  <div
                    className={`confidence-fill ${s.direction}`}
                    style={{ width: `${Math.min(100, s.confidence)}%` }}
                  />
                </div>
                <span className="confidence-num">{s.confidence.toFixed(0)}%</span>
              </div>

              <Sparkline values={s.sparkline} direction={s.direction} />

              <div className="sub-scores">
                <span>เทคนิค: {s.technical_score.toFixed(0)}</span>
                <span>ข่าว: {s.news_score.toFixed(0)}</span>
                <span>
                  ราคา: {s.price.toLocaleString(undefined, { maximumFractionDigits: s.price < 10 ? 4 : 2 })}
                </span>
              </div>

              {s.reasons.length > 0 && (
                <ul className="reasons">
                  {s.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}

              {s.verified && s.confidence >= data.min_confidence_threshold && (
                <span className="verified-tag">✓ ตรวจสอบซ้ำแล้ว / แจ้งเตือนผ่าน Telegram</span>
              )}
            </div>
          ))}
        </div>
      )}

      <footer>
        ข้อมูลราคาจาก Bitkub / Yahoo Finance · ข่าวจาก Google News, Bing News และ Yahoo Finance ·
        วิเคราะห์อัตโนมัติทุก 5 นาทีผ่าน GitHub Actions
      </footer>
    </main>
  );
}
