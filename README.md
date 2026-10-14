# Daily Multibagger Scanner + Short-term Technical Signals

Every weekday after the NSE close this scans NSE small, mid and micro caps for:

1. **Multibagger candidates** (multi-month / multi-year horizon) — original pipeline
2. **Short-term / Swing signals** (1 day – 2 weeks holding) — new technical engine

Both run on the free tier: Yahoo Finance (yfinance) + NSE public endpoints + optional nselib.

## Quick start

```bash
pip install -r requirements.txt

# Multibagger mode (original)
python scan.py --demo
python scan.py --max-fetch 80

# Short-term / Swing mode (NEW)
python scan.py --short --demo
python scan.py --short                  # real scan (uses ~150-180 liquid names)
python scan.py --short --max-scan 100
```

## Short-term signals

The short-term engine produces clean calls in this format:

```
BUY above 305.00
SL  275.00
T1  315   T2  330   T3  350
Holding: 3-12 trading days
Confidence: 78
```

### Features included

- Dynamic Support / Resistance (swing highs & lows)
- Volume-confirmed breakout detection
- ATR-based Stop Loss & progressive Targets
- RSI + trend structure filters
- Market regime filter (risk_on / neutral / risk_off)
- False-breakout protection
- Confidence scoring (0-100)
- Position sizing helper
- Sector relative-strength soft filter
- Clean mobile page at `docs/short.html`

## Architecture

```
scan.py                 # CLI (supports --short)
mb/
  config.py             # ALL thresholds (including SHORT_TERM)
  short_term.py         # NEW – professional short-term engine
  prices.py             # yfinance + regime
  pipeline.py           # orchestration (run + run_short)
  render.py             # index.html + short.html
  ...
docs/
  index.html            # Multibagger daily pick
  short.html            # Short-term signals page
  short_latest.json
data/
  short_signals.json
```

## Configuration

Edit `mb/config.py` → `SHORT_TERM` dict:

- `min_confidence` – minimum score to show a signal (default 58)
- `sl_atr_mult`, `t1_atr_mult` … – ATR multipliers for SL/targets
- `min_volume_surge` – volume confirmation threshold
- `max_scan` – how many liquid names to scan
- `allow_regimes` – which market regimes permit new longs

## Local usage examples

```bash
# Demo (no network)
python scan.py --short --demo

# Real short-term scan
python scan.py --short --max-scan 120

# Original multibagger flow
python scan.py --max-fetch 100
```

## Notes

- Short-term signals are technical only. They do not replace fundamental due diligence.
- Always respect the Stop Loss.
- Free data can be delayed or incomplete; treat this as a screening aid.
- Most short-term trades fail if the broader market turns risk-off.

## Limits

Order book size, export margins and filing PDFs are not parsed by the numbers pipeline. Runway and moat are proxies. Free data can be wrong. This is a screening aid, not investment advice.
