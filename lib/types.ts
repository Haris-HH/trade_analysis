export type Direction = "BUY" | "SELL";

export interface Signal {
  symbol: string;
  display_name: string;
  market: "crypto" | "stock";
  direction: Direction;
  confidence: number;
  technical_score: number;
  news_score: number;
  price: number;
  verified: boolean;
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
