import fs from "fs";
import path from "path";
import type { AnalysisData } from "@/lib/types";
import { Sparkline } from "@/components/Sparkline";
import { AutoRefresh } from "@/components/AutoRefresh";

export const revalidate = 0;

function loadData(): AnalysisData {
  const file = path.join(process.cwd(), "public", "data", "latest.json");
  const raw = fs.readFileSync(file, "utf-8");
  return JSON.parse(raw);
}

function formatPrice(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: value < 10 ? 4 : 2 });
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
  const abstainCount = data.signals.filter((s) => s.abstain).length;
  const signals = data.signals
    .filter((s) => !s.abstain)
    .sort((a, b) => b.confidence - a.confidence);

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
        คำว่า &quot;ซื้อทันที/ขายทันที&quot; และเป้าหมายราคา เป็นการเรียกทิศทางของสัญญาณอัตโนมัติเท่านั้น
        ไม่ใช่คำแนะนำจากผู้เชี่ยวชาญที่ได้รับใบอนุญาตและไม่ใช่การพยากรณ์ที่รับประกันได้
        <br />
        {data.disclaimer}
      </div>

      <div className="meta-row">
        <AutoRefresh generatedAt={data.generated_at} />
        <span className="badge">อัปเดตล่าสุด: {timeAgo(data.generated_at)}</span>
        <span className="badge">เกณฑ์แจ้งเตือน: ≥ {data.min_confidence_threshold}%</span>
        <span className="badge">คริปโตที่สแกน: {data.watchlist_counts.crypto}</span>
        <span className="badge">หุ้นที่สแกน: {data.watchlist_counts.stock}</span>
        {abstainCount > 0 && (
          <span className="badge" title="ข้อมูลราคาน้อยกว่า 60 แท่ง ระบบเลือกไม่ฟันธง (ABSTAIN) แทนการเดา">
            งดออกความเห็น (ABSTAIN): {abstainCount}
          </span>
        )}
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
                <div>
                  <span className={`direction ${s.direction}`}>{s.direction}</span>
                  {s.vetoed && (
                    <span className="veto-badge" title="ผ่านเกณฑ์ความมั่นใจแล้วแต่ถูก veto — ดูเหตุผลด้านล่าง">
                      VETOED
                    </span>
                  )}
                </div>
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
                <span>สอดคล้อง: {(s.agreement * 100).toFixed(0)}%</span>
                <span>ราคา: {formatPrice(s.price)}</span>
              </div>

              {s.reasons.length > 0 && (
                <ul className="reasons">
                  {s.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}

              {s.verified && s.confidence >= data.min_confidence_threshold && (
                <div className={`action-banner ${s.direction}`}>
                  <div className="action-call">
                    {s.direction === "BUY" ? "🟢 แนะนำ: ซื้อทันที (BUY NOW)" : "🔴 แนะนำ: ขายทันที (SELL NOW)"}
                  </div>
                  {s.price_target && (
                    <div className="action-target">
                      เป้าหมาย: <strong>{formatPrice(s.price_target.target_price)}</strong> ภายในวันที่{" "}
                      {s.price_target.target_date} (~{s.price_target.horizon_days} วัน)
                    </div>
                  )}
                  {s.stop_loss !== null && (
                    <div className="action-stoploss">
                      ตัดขาดทุนที่: <strong>{formatPrice(s.stop_loss)}</strong>
                      {s.risk_reward !== null && ` (R:R ${s.risk_reward.toFixed(2)})`}
                    </div>
                  )}
                  <div className="action-caveat">
                    ✓ ตรวจสอบซ้ำแล้ว / แจ้งเตือนผ่าน Telegram — เป้าหมายและจุดตัดขาดทุนเป็นการประมาณจาก ATR ไม่ใช่การรับประกัน
                  </div>
                </div>
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
