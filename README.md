# Trade Signal Dashboard

A free, public dashboard that scans a watchlist of crypto and stocks, scores each
one with **technical indicators + real-time news sentiment**, and sends a
**Telegram alert only when confidence ≥ 70% and the signal survives a second
verification pass**.

> ⚠️ **This is not financial advice.** Confidence scores are a heuristic combination
> of technical indicators and news sentiment — not a statistical guarantee, not
> a licensed recommendation. Always do your own research before trading.

## How it works

```
GitHub Actions (every 5 min, free)
  → scripts/main.py
      1. Fetch prices for ~950 symbols IN PARALLEL: Bitkub's own API (every coin
         listed there) + Yahoo Finance chart API (S&P 500 + liquid Thai SET stocks)
      2. Compute technical score: RSI, MACD cross, EMA20/50 trend, Bollinger %B, volume spike
      3. Skip news lookups for symbols whose technical score alone can't
         mathematically reach 70% (see scoring math below) — keeps Google News
         RSS calls down to a handful of symbols per run instead of ~950
      4. For the rest: fetch recent headlines (Google News RSS), score with VADER sentiment
      5. Combine → confidence score (0-100%), direction BUY/SELL
      6. Candidates ≥ 70%: wait ~45s, re-fetch fresh data for all of them in
         parallel, recompute ("double-check")
      7. Still ≥ 70% + direction unchanged + not in cooldown → send Telegram alert
  → commits public/data/latest.json + data/state.json back to the repo
  → push triggers Vercel to redeploy the dashboard (free Hobby plan)
```

The whole ~950-symbol scan (parallel price fetch + prefilter) typically takes well
under a minute, comfortably inside the 5-minute cron window.

### Why 5 minutes and not faster?

5 minutes is the shortest interval GitHub Actions' `schedule` trigger reliably
supports — GitHub's own docs note shorter intervals aren't guaranteed to run
on time and may be delayed during high load. True second-by-second real-time
would need an always-on server (not a scheduled job), which isn't free. 5 min
is the practical ceiling for this architecture; the per-symbol Telegram
cooldown (`state_store.COOLDOWN_HOURS`) still prevents alert spam regardless
of how often the scan runs.

Everything runs on free tiers: GitHub Actions (unlimited minutes on public repos),
Bitkub/Yahoo Finance/Google News (no API key needed), Vercel Hobby, Telegram Bot API.

### Why not "true" real-time on Vercel alone?

Vercel's free (Hobby) plan only allows cron jobs to run **once per day**, which is
too infrequent for trading signals. GitHub Actions has no such limit on public
repos, so it does the scanning/alerting; Vercel just hosts the static dashboard,
which updates every time the Action pushes new data (~5 min cadence, plus your
Vercel build time, ~1 min).

### Watchlist coverage

- **Crypto: every coin listed on Bitkub** (~360, minus fiat-pegged stablecoins).
  [`scripts/lib/bitkub_source.py`](scripts/lib/bitkub_source.py) fetches the live
  symbol list from `api.bitkub.com/api/market/symbols` on every run — no
  hardcoded list to go stale — and pulls THB-quoted OHLCV candles from Bitkub's
  own `tradingview/history` endpoint, so prices reflect the market you'd
  actually trade on.
- **Stocks: the full S&P 500** + **~90 liquid Thai SET stocks** (SET50 + notable
  SET100 names, individually verified against Yahoo Finance), both tradable
  through **Dime**. These are hardcoded in
  [`scripts/lib/universe.py`](scripts/lib/universe.py) since there's no free
  live screener API for either market — edit that file to add/remove names.

### Why news lookups don't scale with the watchlist size

News sentiment can only ever contribute `NEWS_WEIGHT * 100` points to the
combined score (see `scripts/lib/scoring.py`). With the default 65/35 split,
a symbol needs a technical score of at least ~54 before news could possibly
push it over the 70% alert threshold — so `scripts/main.py` computes technical
scores for the whole universe first (fast, parallel, no news call) and only
fetches news for the small number of symbols that clear that bar. This is what
keeps a ~950-symbol scan fast and inside Google News' informal rate limits.

## Setup

### 1. Push this project to a new GitHub repo

```bash
git init
git add .
git commit -m "Initial commit: trade signal dashboard"
gh repo create trade-signal-dashboard --public --source=. --push
```

(No `gh` CLI? Create an empty repo on github.com, then `git remote add origin <url>` and `git push -u origin main`.)

### 2. Create a Telegram bot and get your chat ID

1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts → copy the **bot token**.
2. Send any message to your new bot, then open in a browser:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   and copy the `chat.id` value from the JSON response (that's your **chat ID**).
   (Or message **@userinfobot** to get your own numeric user/chat ID.)

### 3. Add GitHub Actions secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The scheduled workflow at [`.github/workflows/analyze.yml`](.github/workflows/analyze.yml)
will start running automatically every 5 minutes once it's on the default branch
(you can also trigger it manually from the **Actions** tab via "Run workflow").

### 4. Deploy the dashboard to Vercel (free)

1. Go to [vercel.com/new](https://vercel.com/new), sign in with GitHub, import this repo.
2. Framework preset: **Next.js** (auto-detected). No environment variables needed
   for the dashboard itself — it just reads the committed JSON file.
3. Deploy. Vercel will auto-redeploy on every push the Action makes.

### 5. Local development

```bash
npm install
npm run dev          # dashboard at http://localhost:3000

python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r scripts/requirements.txt
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID if you want to test alerts
DRY_RUN=1 python scripts/main.py   # scans + logs would-be Telegram messages, doesn't send
```

## Tuning

- `scripts/main.py`: `MIN_CONFIDENCE` (default 70), `VERIFY_DELAY_SECONDS` (default 45s re-check delay)
- `scripts/lib/state_store.py`: `COOLDOWN_HOURS` (default 4h between repeat alerts for the same symbol/direction)
- `scripts/lib/scoring.py`: `TECH_WEIGHT` / `NEWS_WEIGHT` (default 65/35 split)
- `scripts/lib/universe.py`: the stock/crypto watchlists
- `.github/workflows/analyze.yml`: cron schedule (`*/15 * * * *`)

## Disclaimer

This project is provided for educational and informational purposes only. It is
not investment advice, and its author is not a licensed financial advisor.
Trading involves risk of loss. Verify signals independently before acting on them.
