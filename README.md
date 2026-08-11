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
      2. Score each with 5 weighted technical factors (trend/momentum/macd/
         mean_reversion/volume), regime-aware (see "Signal engine" below).
         Below 60 candles: no opinion at all (ABSTAIN), not a weak guess
      3. Skip news lookups for symbols whose technical factors alone can't
         mathematically reach 70% confidence even with maximal news — keeps
         news lookups down to a handful of symbols per run instead of ~950
      4. For the rest: fetch + merge recent headlines from 3 free sources
         (Google News RSS, Bing News RSS, and Yahoo Finance's per-ticker feed
         for stocks), de-dupe by title, score with VADER, add as one more
         weighted factor
      5. Aggregate all factors → confidence (magnitude blended with factor
         agreement, capped at 90%) + direction BUY/SELL
      6. VETO: even a high-confidence signal is downgraded if risk:reward < 1.5,
         no valid ATR stop could be computed, or agreement < 60%
      7. Candidates ≥ 70% that survive veto: wait ~45s, re-fetch fresh data for
         all of them in parallel, recompute ("double-check")
      8. Still ≥ 70% + not vetoed + direction unchanged + not in cooldown →
         send an explicit BUY NOW / SELL NOW Telegram alert with an estimated
         price target + date
  → commits public/data/latest.json + data/state.json back to the repo
  → push triggers Vercel to redeploy the dashboard (free Hobby plan)
```

The whole ~950-symbol scan (parallel price fetch + prefilter) typically takes well
under a minute, comfortably inside the 5-minute cron window.

### Signal engine

The confluence engine (`scripts/lib/indicators.py` + `scripts/lib/scoring.py`)
is ported from a more mature companion project (QuantDesk — a separate,
unpublished local project, not part of this repo), which found several sharp
edges the first version of this dashboard didn't handle:

- **Regime detection.** RSI and Bollinger %B are mean-reversion tools —
  correct in a range, actively harmful in a trend (RSI sits above 70 for the
  entire length of a real rally). The engine checks EMA20/EMA50 separation
  first and flips how those two factors are read depending on whether the
  market is trending or ranging.
- **Agreement, not just magnitude.** Confidence isn't a flat weighted sum —
  it blends `|score|` with what fraction of the total factor weight agrees
  with that sign. A score of +0.6 from five agreeing factors means more than
  the same score from one loud factor and four silent ones. Capped at 90%:
  never claim near-certainty.
- **Veto rules.** A signal that clears the confidence bar is still rejected
  if risk:reward < 1.5, no valid ATR-based stop could be computed, or fewer
  than 60% of factors agree. These show up on the dashboard as a `VETOED`
  tag next to the direction, with the reason in the card's reasons list.
- **ABSTAIN.** Under 60 candles, the engine returns no factors at all rather
  than a plausible-looking number computed from insufficient warmup data.
  These symbols are counted (see the "งดออกความเห็น (ABSTAIN)" badge) but
  excluded from the signal list — there's nothing to show.

Missing news is treated as *absent* evidence (the factor is simply omitted,
shrinking coverage), not as a neutral vote — a symbol nobody wrote about
today isn't the same evidence as one with genuinely neutral headlines.

### Why 5 minutes and not faster? (and why it may run even less often than that)

5 minutes is the shortest interval GitHub Actions' `schedule` trigger claims
to support. In practice it's worse than advertised: GitHub's own docs admit
the schedule event "can be delayed during periods of high load," and in
testing this repo's `*/5 * * * *` cron actually fired every **40-90 minutes**,
not 5 — a well-known real-world limitation of GitHub's free scheduler, not a
bug in this code (verified via `GET /repos/{owner}/{repo}/actions/runs`,
looking at the gap between consecutive `schedule`-triggered runs).

**Fix: trigger it externally instead of relying on GitHub's own clock.**
`workflow_dispatch` (already enabled in `analyze.yml`) lets anything with a
GitHub token start the workflow on demand via the API. Point a *reliable*
free external cron service at it and GitHub only has to actually run the
job when told to, not decide when to fire it:

1. Create a GitHub token: **github.com/settings/personal-access-tokens/new**
   → Fine-grained token → Repository access: only this repo → Permissions:
   **Actions: Read and write**. Copy the token (starts with `github_pat_`).
2. Sign up free at [cron-job.org](https://cron-job.org) (supports 1-minute
   intervals on the free tier) and create a cronjob:
   - URL: `https://api.github.com/repos/Haris-HH/trade_analysis/actions/workflows/analyze.yml/dispatches`
   - Method: `POST`
   - Schedule: every 5 minutes
   - Headers: `Authorization: Bearer <your token>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`
   - Body: `{"ref":"main"}`
3. Save and enable it.

The native `schedule:` trigger is left in `analyze.yml` as a free backup —
if the external cron service ever has an outage, GitHub's own (slower,
best-effort) clock still keeps the dashboard updating instead of going
silent entirely.

True second-by-second real-time would still need an always-on server, which
isn't free. The per-symbol Telegram cooldown (`state_store.COOLDOWN_HOURS`)
prevents alert spam regardless of how often the scan actually runs.

Everything runs on free tiers: GitHub Actions (unlimited minutes on public repos),
Bitkub/Yahoo Finance/Google News/Bing News (no API key needed), Vercel Hobby, Telegram Bot API.

### Price targets and the "BUY NOW / SELL NOW" call

Once a signal has cleared both confidence checks, the dashboard and Telegram
alert state the call directly ("🟢 แนะนำ: ซื้อทันที (BUY NOW)") along with an
estimated **price target and target date**, computed by
[`scripts/lib/price_target.py`](scripts/lib/price_target.py):

1. Target distance = 15x the 14-period Average True Range (a "measured move"
   projection — a standard technical-analysis technique, not a statistical model).
2. Time-to-target = that distance divided by the recent average per-bar price
   move, converted to a calendar date using the chart's own bar interval
   (with a trading-hours/weekend adjustment for stocks, since markets close
   overnight but crypto trades 24/7).

This is explicitly a heuristic, not a forecast — it answers "if price kept
moving at its recent pace, when would it cover this distance?", not "this is
what will happen." Both the dashboard banner and the Telegram message carry
that caveat next to the number. There is still no licensed advisor behind
this — "BUY NOW" here means "the automated signal crossed the alert
threshold," not personalized financial advice.

Alongside the target, the same banner shows a **stop-loss price and
risk:reward ratio** — the same ATR-scaled stop (`ATR_STOP_MULTIPLE` = 1.5x)
already computed internally for the risk:reward veto check (see "Signal
engine" above), just surfaced directly instead of only being used to decide
whether to veto the signal.

### Charts

Each card on the dashboard includes a sparkline built from the same price
series (`scripts/lib/chart.py`) that fed the technical indicators — the exact
history the BUY/SELL call is based on, not a separate/prettier feed. It's
computed server-side and rendered as inline SVG (`components/Sparkline.tsx`),
so there's no charting library dependency.

### Auto-refresh

An open browser tab updates itself when a new scan cycle finishes — no manual
reload needed. `components/AutoRefresh.tsx` polls `public/data/latest.json`
every 30s and calls Next.js's `router.refresh()` if `generated_at` has moved
forward, which re-renders the page with fresh data in place (no full page
reload, scroll position kept). The small pulsing dot next to "อัปเดตอัตโนมัติ"
in the header turns red if a poll fails (e.g. you're offline).

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

News is one factor among six, weighted 0.10 out of a 1.00 total (see
`WEIGHTS` in `scripts/lib/scoring.py`), so it can only ever push the
confidence so far. `scoring.best_case_confidence()` computes what confidence
*would* result if news voted maximally in the technical read's favor — if
even that can't reach 70%, there's no point spending an HTTP request to find
out what the news actually says. `scripts/main.py` runs this check for the
whole universe first (fast, parallel, no network call) and only fetches news
for the small number of symbols that clear it. This is what keeps a
~950-symbol scan fast and inside these free news sources' informal rate limits.

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
- `scripts/lib/scoring.py`: `WEIGHTS` (per-factor weights), `CONFIDENCE_CAP` (90), `MIN_AGREEMENT` (0.6),
  `MIN_RR` (1.5), `ATR_STOP_MULTIPLE` / `ATR_TARGET_MULTIPLE` (1.5x / 2.5x, used for the veto check —
  not the same as the longer-horizon target shown on the dashboard, see `price_target.py`)
- `scripts/lib/indicators.py`: `MIN_CANDLES` (60 — below this, a symbol abstains instead of guessing),
  `TREND_THRESHOLD` (0.8% EMA separation before a market counts as "trending")
- `scripts/lib/state_store.py`: `COOLDOWN_HOURS` (default 4h between repeat alerts for the same symbol/direction)
- `scripts/lib/universe.py`: the stock watchlists (crypto is fetched live, see above)
- `.github/workflows/analyze.yml`: cron schedule (`*/5 * * * *`)

## Disclaimer

This project is provided for educational and informational purposes only. It is
not investment advice, and its author is not a licensed financial advisor.
Trading involves risk of loss. Verify signals independently before acting on them.
