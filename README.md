# Daily multibagger scanner

Every weekday after the NSE close this scans NSE small, mid and micro caps, scores each on ten pillars,
runs AI due diligence on the top finalists, and publishes **one candidate with its proof** to GitHub Pages
(readable on your phone). Every pick is logged, so the page shows a live track record against the Nifty.

## What it checks

| Layer | What | Source |
|---|---|---|
| Liquidity and technicals | turnover, 200-day trend, 6-month strength vs Nifty, volume build-up | Yahoo prices |
| Growth and proof | revenue and profit CAGR, latest-quarter growth and acceleration, margin trend | Yahoo statements |
| Capital and earnings quality | ROCE and trend, debt, dilution, **cash flow vs profit**, **interest coverage**, **receivable days** | Yahoo statements |
| Runway and moat (proxies) | theme keywords, small revenue base, ROCE stability | Yahoo + keywords |
| Discovery | market cap, institutional holding, analyst count | Yahoo |
| Ownership | promoter holding trend, pledge, insider buying, FII/DII trend | NSE (undocumented endpoints) |
| Catalysts | order wins, expansion and capacity doubling, acquisitions, export orders, approvals, bonus/split, negatives | NSE filings + capex/CWIP/goodwill |
| **AI due diligence** | management record, SEBI/litigation, auditor issues, order book and capex commentary | Gemini or Claude with web search |

Hard rejects: financial companies, stale or suspect data, tiny or huge caps, unprofitable or slow growers, pledge above 25%,
negative filings (pledge invocation, distress, governance, SEBI), more than one high red flag, and an AI **red** verdict.
The AI never changes the score. It only gates, and a "green" with no cited source is downgraded to "yellow".
Yesterday's pick is kept unless beaten by 3+ points, so the pick doesn't flip on noise.

## Set up (about 15 minutes)

1. Create a GitHub repo and upload everything here (keep `.github/workflows/daily.yml`).
2. **Settings > Actions > General > Workflow permissions**: Read and write.
3. **Settings > Pages**: Deploy from a branch, `main`, folder `/docs`.
4. **Settings > Secrets and variables > Actions**, add what you want (all optional):
   - `GEMINI_API_KEY`: free key from https://aistudio.google.com/apikey (AI due diligence)
   - `ANTHROPIC_API_KEY`: paid alternative or backup (uses Claude with web search)
   - `NTFY_TOPIC`: pick any hard-to-guess name, install the free ntfy app, subscribe to it, get the daily pick as a phone alert
   - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: alternative alert channel
5. **Actions > Daily multibagger scan > Run workflow** with `max_fetch` = `300`. Repeat 2 to 4 times over a couple of days
   to fill the fundamentals cache. After that it only tops up the oldest entries.
6. Your page: `https://<username>.github.io/<repo>/`

## First real run: verify the data before trusting it

Nothing here has been run against live Yahoo, NSE or Gemini from where it was built. Check one company you know:

    pip install -r requirements.txt
    python scan.py --check ASTRAMICRO.NS

It prints every metric, the pillar scores and the flags. Compare a few numbers with the company's results.
After the first workflow run, open `data/signals_debug.json`: it shows which NSE sources worked and the field names
returned, so a broken parser can be fixed quickly. If the page says AI due diligence "failed", the reason is printed there
(commonly a model name your key can't use: set the `GEMINI_MODELS` environment variable to a comma-separated list).

## Preview and tests

    python scan.py --demo                 # synthetic companies, no network or keys
    python tests/test_signals.py          # parsers
    python tests/test_diligence.py        # AI module and notifications, mocked
    python tests/test_pipeline.py         # gate, stability, track record

## If something fails

- **NSE list blocked**: add tickers to `universe_extra.txt` or commit `data/universe.csv` with a `ticker` column.
- **NSE signals blocked on GitHub**: the page says so and ranks on price and fundamentals only.
- **Yahoo rate limits**: the run stops early after 15 failures in a row and keeps what it has. Re-run later.
- **No pick yet**: normal until the cache fills.

## Limits

Order book size, export margins and filing PDFs are not parsed by the numbers pipeline; the AI step reports what it finds
with sources, and you must open them. Runway and moat are proxies. The score weights are reasoned starting points, not fitted
to history, so the track record is the real test (give it 20+ picks). Free data can be wrong. This is a screening aid,
not investment advice, and most early-stage picks fail. Tune `CFG` and `WEIGHTS` at the top of `scan.py`.
