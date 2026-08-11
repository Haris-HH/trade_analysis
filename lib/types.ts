export type Direction = "BUY" | "SELL";

export interface PriceTarget {
  target_price: number;
  target_date: string;
  horizon_days: number;
  method: string;
}

export interface Signal {
  symbol: string;
  display_name: string;
  market: "crypto" | "stock";
  direction: Direction;
  confidence: number;
  agreement: number;
  technical_score: number;
  news_score: number;
  price: number;
  sparkline: number[];
  price_target: PriceTarget | null;
  stop_loss: number | null;
  risk_reward: number | null;
  verified: boolean;
  vetoed: boolean;
  abstain: boolean;
  reasons: string[];
  last_alert_at: string | null;
}

export interface AnalysisData {
  generated_at: string;
  disclaimer: string;
  min_confidence_threshold: number;
  watchlist_counts: { crypto: number; stock: number };
  signals: Signal[];
}
