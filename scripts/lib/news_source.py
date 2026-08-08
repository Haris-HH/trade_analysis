"""Real-time news sentiment via Google News RSS (free, no API key) + VADER."""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone

import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def fetch_headlines(query: str, max_age_hours: int = 24, limit: int = 15) -> list[dict]:
    url = GOOGLE_NEWS_RSS.format(query=urllib.parse.quote(query))
    feed = feedparser.parse(url)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    items = []
    for entry in feed.entries[: limit * 2]:
        published = None
        if getattr(entry, "published_parsed", None):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if published and published < cutoff:
            continue
        items.append({
            "title": entry.get("title", ""),
            "published": published.isoformat() if published else None,
            "source": entry.get("source", {}).get("title", ""),
        })
        if len(items) >= limit:
            break
    return items


def compute_news_score(query: str) -> tuple[float, list[str], int]:
    """Returns (signed score in [-100, 100], reasons, article_count)."""
    try:
        headlines = fetch_headlines(query)
    except Exception as exc:  # network hiccup shouldn't kill the whole run
        return 0.0, [f"ดึงข่าวไม่สำเร็จ: {exc}"], 0

    if not headlines:
        return 0.0, ["ไม่พบข่าวล่าสุดในช่วง 24 ชม."], 0

    compounds = []
    for h in headlines:
        vs = _analyzer.polarity_scores(h["title"])
        compounds.append(vs["compound"])

    avg = sum(compounds) / len(compounds)
    score = max(-100.0, min(100.0, avg * 100))

    reasons = []
    if score >= 20:
        reasons.append(f"ข่าวเชิงบวก {len(headlines)} ชิ้นใน 24 ชม. (sentiment {avg:+.2f})")
    elif score <= -20:
        reasons.append(f"ข่าวเชิงลบ {len(headlines)} ชิ้นใน 24 ชม. (sentiment {avg:+.2f})")
    else:
        reasons.append(f"ข่าวเป็นกลาง {len(headlines)} ชิ้นใน 24 ชม. (sentiment {avg:+.2f})")

    return score, reasons, len(headlines)
