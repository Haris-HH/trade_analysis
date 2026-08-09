"""Real-time news sentiment aggregated from multiple free, no-key RSS sources:

  - Google News RSS (general web news search)
  - Bing News RSS (independent index, catches stories Google News misses)
  - Yahoo Finance's per-ticker news feed (stocks only, most relevant/precise)

Headlines from all applicable sources are merged, de-duplicated by title, and
scored together with VADER so one flaky/rate-limited source doesn't blank out
the signal.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone

import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
BING_NEWS_RSS = "https://www.bing.com/news/search?q={query}&format=RSS&mkt=en-US"
YAHOO_FINANCE_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _parse_feed(url: str, max_age_hours: int, limit: int) -> list[dict]:
    feed = feedparser.parse(url, request_headers=HEADERS)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    items = []
    for entry in feed.entries[: limit * 2]:
        published = None
        if getattr(entry, "published_parsed", None):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if published and published < cutoff:
            continue
        title = entry.get("title", "").strip()
        if not title:
            continue
        items.append({
            "title": title,
            "published": published.isoformat() if published else None,
            "source": entry.get("source", {}).get("title", ""),
        })
        if len(items) >= limit:
            break
    return items


def fetch_google(query: str, max_age_hours: int = 24, limit: int = 12) -> list[dict]:
    url = GOOGLE_NEWS_RSS.format(query=urllib.parse.quote(query))
    return _parse_feed(url, max_age_hours, limit)


def fetch_bing(query: str, max_age_hours: int = 24, limit: int = 12) -> list[dict]:
    url = BING_NEWS_RSS.format(query=urllib.parse.quote(query))
    return _parse_feed(url, max_age_hours, limit)


def fetch_yahoo_finance(ticker: str, max_age_hours: int = 24, limit: int = 12) -> list[dict]:
    url = YAHOO_FINANCE_RSS.format(ticker=urllib.parse.quote(ticker))
    return _parse_feed(url, max_age_hours, limit)


def fetch_headlines(query: str, ticker: str | None = None) -> list[dict]:
    """Merge headlines from every applicable source, de-duped by title."""
    all_items: list[dict] = []
    for fetch in (
        lambda: fetch_google(query),
        lambda: fetch_bing(query),
        *([lambda: fetch_yahoo_finance(ticker)] if ticker else []),
    ):
        try:
            all_items.extend(fetch())
        except Exception as exc:
            print(f"[news] a source failed for {query!r}: {exc}")

    seen = set()
    deduped = []
    for item in all_items:
        key = item["title"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def compute_news_score(query: str, ticker: str | None = None) -> tuple[float, list[str], int]:
    """Returns (signed score in [-100, 100], reasons, article_count)."""
    headlines = fetch_headlines(query, ticker)

    if not headlines:
        return 0.0, ["ไม่พบข่าวล่าสุดในช่วง 24 ชม. (ค้นจาก Google News, Bing News)"], 0

    compounds = [_analyzer.polarity_scores(h["title"])["compound"] for h in headlines]
    avg = sum(compounds) / len(compounds)
    score = max(-100.0, min(100.0, avg * 100))

    reasons = []
    if score >= 20:
        reasons.append(f"ข่าวเชิงบวก {len(headlines)} ชิ้นใน 24 ชม. จากหลายแหล่ง (sentiment {avg:+.2f})")
    elif score <= -20:
        reasons.append(f"ข่าวเชิงลบ {len(headlines)} ชิ้นใน 24 ชม. จากหลายแหล่ง (sentiment {avg:+.2f})")
    else:
        reasons.append(f"ข่าวเป็นกลาง {len(headlines)} ชิ้นใน 24 ชม. จากหลายแหล่ง (sentiment {avg:+.2f})")

    return score, reasons, len(headlines)
