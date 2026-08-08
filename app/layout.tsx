import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Trade Signal Dashboard",
  description: "Technical + news-sentiment trade signal scanner for stocks and crypto (educational, not financial advice).",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
