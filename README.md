# Daily multibagger scanner (v2)

Every weekday after the NSE close this scans NSE small, mid and micro caps, scores each on ten pillars,
runs AI due diligence on the top finalists, and publishes **one candidate with its proof** to GitHub Pages
(readable on your phone). Every pick is logged, so the page shows a live track record against the Nifty.

**Free-tier only:** Yahoo Finance (yfinance) + NSE public endpoints + optional [nselib](https://github.com/RuchiTanmay/nselib) for delivery %, Gemini free tier for AI diligence.

## Architecture (refactored)

```
scan.py                 # thin CLI
mb/
  config.py             # ALL thresholds & weights in one place
  utils.py              # numerics, JSON I/O
  universe.py           # NSE index constituents
  prices.py             # yfinance bulk prices + optional nselib delivery %
  fundamentals.py       # Yahoo statements → flat metrics
  scoring.py            # 10 pillars, red flags, hard gates
  evidence.py           # human-readable proof rows + thesis + exits
  signals.py            # NSE announcements / ownership (fail-soft)
  diligence.py          # Gemini / Claude gate (never changes the score)
  notify.py             # ntfy + Telegram
  render.py             # mobile-first GitHub Pages HTML
  pipeline.py           # orchestration
```

## What it checks

| Layer | What | Source |
|---|---|---|
| Liquidity and technicals | turnover, 200-day trend, 6-month strength vs Nifty, volume, delivery % | Yahoo + nselib |
| Growth and proof | revenue/profit CAGR, quarterly acceleration, margin trend | Yahoo statements |
| Capital and earnings quality | ROCE, debt, dilution, cash flow vs profit, interest coverage, receivables | Yahoo |
| Runway and moat (proxies) | theme keywords, small revenue base, ROCE stability | Yahoo + keywords |
| Discovery | market cap, institutional holding, analyst count | Yahoo |
| Ownership | promoter trend, pledge, insider buying, FII/DII | NSE (undocumented) |
| Catalysts | order wins, expansion, capacity doubling, acquisitions, exports, approvals, negatives | NSE filings + CWIP |
| **AI due diligence** | management, SEBI/litigation, auditor, order book / capex commentary | Gemini (free) or Claude |

### Hard rejects (tuned for multibagger quality)

- Financial companies
- Stale or suspect data
- Market cap outside Rs 400–25,000 cr
- Unprofitable or slow growers (<15% growth)
- ROCE < 12%, D/E > 1.2, dilution > 12%
- Promoter pledge > 20%
- Negative filings (pledge invocation, distress, governance, SEBI)
- More than one high red flag
- AI **red** verdict

The AI never changes the score. It only gates, and a "green" with no cited source is downgraded to "yellow".
Yesterday's pick is kept unless beaten by 3.5+ points (hysteresis).

## Set up (~15 minutes)

1. Create a GitHub repo and upload everything (keep `.github/workflows/daily.yml`).
2. **Settings > Actions > General > Workflow permissions**: Read and write.
3. **Settings > Pages**: Deploy from branch `main`, folder `/docs`.
4. **Settings > Secrets and variables > Actions** (all optional):
   - `GEMINI_API_KEY` — free key from https://aistudio.google.com/apikey
   - `ANTHROPIC_API_KEY` — paid alternative / backup
   - `NTFY_TOPIC` — free phone alerts via the ntfy app
   - `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
5. **Actions > Daily multibagger scan > Run workflow** with `max_fetch = 300`. Repeat 2–4 times over a couple of days to fill the fundamentals cache. After that it only tops up the oldest entries.
6. Your page: `https://<username>.github.io/<repo>/`

## Local usage

```bash
pip install -r requirements.txt

python scan.py --demo                 # synthetic companies, no network
python scan.py --check ASTRAMICRO.NS  # one ticker: every metric + pillars + flags
python scan.py --max-fetch 50         # real scan (gradual fundamentals refresh)

python tests/test_signals.py
python tests/test_diligence.py
python tests/test_pipeline.py
```

## Tuning

Edit **`mb/config.py` only**:

- `CFG` — market-cap band, growth floor, pledge limit, hysteresis, pillar coverage, …
- `WEIGHTS` — pillar importance (proof and quality are weighted highest by default)
- `THEMES` / `MOAT_WORDS` — keyword maps for runway/moat

After ~20 live picks, compare track-record excess return and consider re-weighting empirically.

## Data sources (all free)

| Source | Used for | Notes |
|---|---|---|
| **yfinance** | Prices, financial statements, ratios | Primary; gradual cache avoids rate limits |
| **NSE public CSVs / JSON** | Universe, announcements, shareholding, insider | Fail-soft; sometimes blocked on cloud IPs |
| **nselib** (optional) | Delivery % enrichment for top candidates | `pip install nselib` |
| **Gemini free tier** | Qualitative due diligence gate | Set `GEMINI_API_KEY` |

## What changed in v2

- Modular package (`mb/`) instead of a 1,100-line `scan.py`
- Central config; stricter multibagger gates (ROCE, D/E, dilution, growth floor, mcap band)
- Higher weight on **proof** and **quality** pillars
- Optional **nselib** delivery-% confirmation
- Acquisition-led growth flagged as medium risk
- Demo end-to-end test in CI
- Cleaner evidence / thesis / exit-trigger text

## Limits

Order book size, export margins and filing PDFs are not parsed by the numbers pipeline; the AI step reports what it finds with sources — you must open them. Runway and moat are proxies. Free data can be wrong. This is a screening aid, not investment advice, and most early-stage picks fail.
