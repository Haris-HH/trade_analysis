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
      2. Score each with 11 weighted factors (trend/momentum/macd/
         mean_reversion/volume/volume_profile/smart_money/trend_confluence/
         fundamental/market_mood/ichimoku), regime-aware (see "Signal
         engine" below).
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
      9. (Optional, off by default) Auto-trader: places a real Bitkub market
         BUY for double-checked crypto candidates ≥ a stricter confidence bar,
         and auto-sells any open position at +5% take-profit or -8%
         stop-loss — see "Auto-trading" below
  → commits public/data/latest.json + data/state.json + data/positions.json +
    data/trade_log.json + data/coingecko_cache.json back to the repo
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
- **Three extra confluence factors**, heuristic ports of TradingView tools
  the user also watches manually, since a Python engine has no chart to
  attach a Pine Script overlay to (`scripts/lib/indicators.py`):
  - `trend_confluence` — approximates justUncle's **Big Snapper** alert,
    per its own how-to-use video ([ORC Crypto](https://youtube.com/watch?v=aOYth3R0IaE)):
    trend from a single slow MA (EMA 50 here — candle above/below it), a
    trigger event (a SuperTrend(10, 3.0) flip stands in for Big Snapper's
    own undisclosed signal-bar formula), and a same-colored confirmation
    candle, with a few bars' grace if the trigger candle itself closes the
    wrong color (matching the video's "wait for the next candle" rule) and
    a hard skip — not just a lower vote — for any trigger on the wrong side
    of the MA, which the video calls an explicit "inverse/error" signal.
  - `smart_money` — approximates chartPrime's **Smart Money Breakouts** +
    MyTradingCoder's **magnified order block**: detects a break of
    structure (price closing beyond the last confirmed swing high/low,
    found via a 5-bar fractal) and checks whether price has pulled back
    into the order block (the last opposite-colored candle before the
    breakout leg) for a higher-quality entry read.
  - `volume_profile` — a point-of-control / value-area read: bins the last
    100 candles' volume by price, finds the high-volume node (POC) and the
    70%-of-volume value area, and votes on whether price is breaking out of
    or drifting back toward that zone.
  These are optional like every other factor — a symbol without a fresh
  break of structure simply omits `smart_money` for that scan rather than
  forcing an opinion (same ABSTAIN-style pattern as the other factors).
- **Two crypto-only factors covering fundamentals and market mood** — the
  legs of the user's own 4-part checklist (fundamental analysis, news &
  sentiment) that price/volume data alone can't reach:
  - `fundamental` (`scripts/lib/fundamentals.py`) — market-cap rank +
    circulating/total supply ratio from CoinGecko's free `/coins/markets`
    endpoint, as a computable proxy for "มีโปรเจกต์และทีมงานเบื้องหลังที่
    น่าเชื่อถือหรือไม่" (team/project credibility can't be automated, but a
    large, long-lived market cap is the closest available signal) and
    "ดู Total Supply และ Circulating Supply" (a low circulating/total ratio
    flags dilution risk from future token unlocks). Fetched once per scan
    (not once per symbol — ~1000 coins across 4 pages), cached to
    `data/coingecko_cache.json` with a 12h TTL, and **committed back to the
    repo by the CI workflow** (same pattern as `data/state.json`) since
    GitHub Actions runners are ephemeral and would otherwise lose the cache
    every run.
  - `market_mood` (`scripts/lib/fear_greed.py`) — Alternative.me's Fear &
    Greed Index (0–100), fetched once per scan and shared across every
    crypto symbol in that cycle, voted contrarian: extreme fear tilts
    toward BUY, extreme greed tilts toward caution — directly the
    checklist's "วัดอารมณ์ตลาด (Fear and Greed Index) ว่าช่วงนั้นคนโลภหรือ
    กลัวมากเกินไป".
  Both are omitted (not forced to a weak vote) when data is unavailable,
  and both are skipped entirely for stocks, which have neither a supply
  concept nor crypto-specific sentiment.
- **`ichimoku`** — the one indicator from Bitkub's own "Indicator" blog
  guide (bitkub.com/th/blog/indicator-8eefc6fd5a53) not already covered
  above: price position relative to the Ichimoku Cloud (properly
  time-shifted 26 bars, matching what the chart actually displays — above
  the cloud is an uptrend, below is a downtrend, inside is genuinely
  undecided, straight from the article) plus the Tenkan/Kijun cross as a
  secondary momentum confirmation. Needs ≥78 candles; omitted below that.

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

### Auto-trading (optional, off by default)

[`scripts/lib/auto_trader.py`](scripts/lib/auto_trader.py) can place real
Bitkub market orders using the same indicator-driven signal engine described
above — it doesn't run a separate analysis, it reuses whichever crypto
signals just cleared the double-check re-verification pass that Telegram
BUY-NOW alerts use (`indicators.py` + `scoring.py`'s regime-aware confluence
engine, ATR-based stop/target, veto rules).

- **Entry (BUY):** a crypto symbol whose signal survived re-verification —
  `direction == BUY`, not vetoed, confidence ≥ `AUTO_TRADE_MIN_CONFIDENCE`
  (default 75, stricter than the 70% alert bar since real money is on the
  line) — triggers a market buy, as long as that ticker isn't already held
  and `AUTO_TRADE_MAX_POSITIONS` (default 3) isn't already reached. Position
  **size** is `AUTO_TRADE_AMOUNT_THB` (default 100 THB) flat per trade,
  unless risk-based sizing is enabled — see below.
- **Exit (SELL):** every open position is checked against the current scan's
  price and closed automatically — take-profit at
  `AUTO_TRADE_TAKE_PROFIT_PCT` (default **+5%**), or stop-loss at
  `AUTO_TRADE_STOP_LOSS_PCT` (default -8%, protects capital if a position
  keeps losing — set to `0` to disable and only ever exit at take-profit).
- **Risk-based position sizing** (`scripts/lib/auto_trader.py`
  `_position_size_thb`, off by default): set `AUTO_TRADE_RISK_PCT` to size
  each trade so that hitting the *signal's own* ATR-based stop
  (`r["stop_loss"]`, the same one behind the veto's risk:reward check — not
  this module's fixed `AUTO_TRADE_STOP_LOSS_PCT` exit) costs exactly that %
  of account equity (free THB + the market value of every open position),
  instead of every trade risking the same flat THB amount regardless of how
  close or far its stop actually is. Ported from the account's own
  **ORC_CRYPTO Position Sizer** tool
  (`ORC_CRYPTO_PositionSizer_FREE_V4.html`) and its companion video
  ([youtube.com/watch?v=c6DFdPf5bug](https://youtube.com/watch?v=c6DFdPf5bug)),
  which stresses two things this port keeps: round-trip fees
  (`BITKUB_FEE_PCT`, default 0.25% per side, doubled) must be included in
  the sizing math or the position comes out too large, and the video's own
  risk tiers — 0.5% conservative, 1% standard, 2% aggressive, 3–5% "pro" —
  are a reasonable starting point for `AUTO_TRADE_RISK_PCT`. Clamped to
  never exceed account equity and never fall below a 10 THB practical
  minimum order. Never fetches Bitkub balances during `DRY_RUN` (keeping
  the "DRY_RUN never calls Bitkub" guarantee below intact) — it just falls
  back to the flat `AUTO_TRADE_AMOUNT_THB` there instead.
- Positions persist in [`data/positions.json`](data/positions.json)
  (committed by the Action, same pattern as `data/state.json`); every
  executed trade is appended to [`data/trade_log.json`](data/trade_log.json)
  for a permanent audit trail. Both are also included as `open_positions` /
  implicitly reflected in `public/data/latest.json` for the current state.
- Every executed trade sends its own Telegram message (🤖 Auto-trade
  BUY/SELL), separate from the signal alert. Whenever at least one position
  closes in a scan cycle, a second message follows with portfolio-level
  performance — win rate, profit factor, average R-multiple, total P&L, max
  drawdown (`scripts/lib/trade_stats.py`) — the same analytics the Position
  Sizer's own trade journal computes, so the numbers aren't only ever
  visible one trade at a time.

**Off by default, two independent switches:**

1. `BITKUB_API_KEY` / `BITKUB_API_SECRET` must be set — create the key at
   [bitkub.com](https://www.bitkub.com) under **API Management**, scoped to
   **Trade** permission only (never enable withdrawal on a bot key), and
   IP-whitelist it if you can.
2. `AUTO_TRADE_ENABLED` must be exactly `"1"` — even with valid keys above,
   nothing trades until this is explicitly set.

Test first with `DRY_RUN=1` (the same flag already used for Telegram) — it
logs every order the bot *would* place, and the would-be Telegram messages,
without calling Bitkub or spending real money:

```bash
BITKUB_API_KEY=... BITKUB_API_SECRET=... AUTO_TRADE_ENABLED=1 DRY_RUN=1 python scripts/main.py
```

Add these as **GitHub Actions secrets** the same way as `TELEGRAM_BOT_TOKEN`
(Settings → Secrets and variables → Actions):
`BITKUB_API_KEY`, `BITKUB_API_SECRET`, `AUTO_TRADE_ENABLED`, and optionally
`AUTO_TRADE_AMOUNT_THB` / `AUTO_TRADE_MAX_POSITIONS` /
`AUTO_TRADE_MIN_CONFIDENCE` / `AUTO_TRADE_TAKE_PROFIT_PCT` /
`AUTO_TRADE_STOP_LOSS_PCT` / `AUTO_TRADE_RISK_PCT` / `BITKUB_FEE_PCT` to
override the defaults above.

> ⚠️ This places real orders with real money once enabled. The signal engine
> is a heuristic (see disclaimer above) — it can and will be wrong. Start
> with a small `AUTO_TRADE_AMOUNT_THB`, verify behavior with `DRY_RUN=1`
> first, and never risk more than you can afford to lose entirely.

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

### 5. (Optional) Enable the alert-mode radio buttons

The dashboard header has radio buttons — **Crypto only / Stocks only / Both / None** —
that control which market(s) are allowed to trigger a Telegram alert. The choice is
stored in [`data/alert_settings.json`](data/alert_settings.json), which
`scripts/main.py` reads on every scan (`market_alerts_allowed()` in `main.py`) before
sending, and the dashboard's page and cards keep showing all signals either way — only
the Telegram send is filtered.

Because Vercel's filesystem is read-only at runtime, saving a new choice works by
committing the updated `data/alert_settings.json` straight to GitHub via its Contents
API (`app/api/alert-settings/route.ts`), the same way the GitHub Action commits scan
results. That needs its own token, separate from the Action's `GITHUB_TOKEN` secret
(which only exists inside Action runs) — add these as **Vercel project env vars**
(Project → Settings → Environment Variables):

- `GITHUB_TOKEN` — a fine-grained PAT ([github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new)) scoped to only this repo, with **Contents: Read and write**
- `GITHUB_REPO` — `owner/repo`, e.g. `Haris-HH/trade_analysis`
- `GITHUB_BRANCH` — `main` (optional, defaults to `main`)

Without these two set, the radio buttons still render but saving fails with a clear
error instead of silently doing nothing.

### 6. (Optional) Enable auto-trading

Off by default — see "Auto-trading" above for how it works and the risks. To
enable it, add these as **GitHub Actions secrets** (Settings → Secrets and
variables → Actions):

- `BITKUB_API_KEY` / `BITKUB_API_SECRET` — from [bitkub.com](https://www.bitkub.com) → API Management, **Trade permission only**, no withdrawal
- `AUTO_TRADE_ENABLED` — set to `1` to actually trade (test with `DRY_RUN=1` locally first, see step 7)
- Optionally override `AUTO_TRADE_AMOUNT_THB`, `AUTO_TRADE_MAX_POSITIONS`, `AUTO_TRADE_MIN_CONFIDENCE`, `AUTO_TRADE_TAKE_PROFIT_PCT`, `AUTO_TRADE_STOP_LOSS_PCT`, `AUTO_TRADE_RISK_PCT`, `BITKUB_FEE_PCT`

### 7. Local development

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
  `TREND_THRESHOLD` (0.8% EMA separation before a market counts as "trending"); `_supertrend()`'s
  `period`/`multiplier` (10 / 3.0), `_compute_trend_confluence()`'s slow MA span (50) and `CONFIRM_WINDOW` (3 bars),
  `_compute_smart_money()`'s swing lookback/arm (60 bars / 2) and `FRESH_BARS` (6), and
  `_compute_volume_profile()`'s `bins`/`lookback` (20 / 100 candles) — all tunable, same file
  and `_compute_ichimoku()`'s window1/window2/window3 (9 / 26 / 52 — the standard Ichimoku periods)
- `scripts/lib/fundamentals.py`: `PAGES` (4 — top 1000 coins by market cap), `CACHE_TTL_SECONDS` (12h)
- `scripts/lib/fear_greed.py`: no knobs — one shared value fetched fresh every scan cycle
- `scripts/lib/state_store.py`: `COOLDOWN_HOURS` (default 4h between repeat alerts for the same symbol/direction)
- `data/alert_settings.json`: `alert_mode` (`crypto` / `stock` / `both` / `none`) — which market(s) may send a
  Telegram alert; editable via the dashboard's radio buttons (see setup step 5) or by hand
- `scripts/lib/universe.py`: the stock watchlists (crypto is fetched live, see above)
- `.github/workflows/analyze.yml`: cron schedule (`*/5 * * * *`)
- `scripts/lib/auto_trader.py` (see "Auto-trading" above, off by default): `AUTO_TRADE_ENABLED` (must be `"1"`),
  `AUTO_TRADE_AMOUNT_THB` (100), `AUTO_TRADE_MAX_POSITIONS` (3), `AUTO_TRADE_MIN_CONFIDENCE` (75),
  `AUTO_TRADE_TAKE_PROFIT_PCT` (5), `AUTO_TRADE_STOP_LOSS_PCT` (8, `0` disables it),
  `AUTO_TRADE_RISK_PCT` (0 — disabled, flat `AUTO_TRADE_AMOUNT_THB` sizing; the video's own tiers are
  0.5/1/2/3-5 for conservative/standard/aggressive/pro), `BITKUB_FEE_PCT` (0.25, per side),
  `MIN_ORDER_THB` (10, hardcoded floor for risk-based sizing)
- `scripts/lib/trade_stats.py`: `compute_stats()`'s R-multiple approximation uses
  `auto_trader.STOP_LOSS_PCT` as the risk denominator — override that, not a separate constant here

## Disclaimer

This project is provided for educational and informational purposes only. It is
not investment advice, and its author is not a licensed financial advisor.
Trading involves risk of loss. Verify signals independently before acting on them.
