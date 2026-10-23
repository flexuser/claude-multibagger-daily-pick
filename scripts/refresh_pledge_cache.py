#!/usr/bin/env python3
"""
Free-only: refresh data/pledge_cache.json for the daily GitHub job.

Run this on a NORMAL (home/office) IP — not GitHub Actions — about
once a week or after new quarterly SHP filings.

Sources (all free, no broker):
  1. NSE corporate-pledgedata JSON (when unblocked)
  2. NSE shareholding master (pledge field if present)
  3. Screener investors/pledged endpoint (often empty; kept as try)
  4. Existing cache (never wipe unknown tickers)

Usage:
  # watchlist + optional universe sample
  python scripts/refresh_pledge_cache.py --tickers JSLL,NEWGEN,POWERMECH,SKIPPER

  # from a text file (one symbol per line)
  python scripts/refresh_pledge_cache.py --file data/pledge_universe.txt

  # top liquid names from last fundamentals cache
  python scripts/refresh_pledge_cache.py --from-fundamentals --limit 80

  # dry-run
  python scripts/refresh_pledge_cache.py --tickers TCS,RELIANCE --dry-run

Then commit data/pledge_cache.json so Actions can use it without NSE.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mb.config import DATA, CACHE_JSON
from mb.utils import load_json, save_json
from mb.signals import NSEClient
from mb.pledge_sources import (
    from_nse_pledge_api,
    from_nse_shareholding_master,
    from_screener,
    from_local_cache,
    CACHE_JSON as PLEDGE_CACHE,
)


def symbols_from_fundamentals(limit: int) -> list[str]:
    fund = load_json(CACHE_JSON, {})
    rows = []
    for tk, f in fund.items():
        if not isinstance(f, dict) or f.get("failed"):
            continue
        mc = f.get("mcap_cr")
        if mc is None:
            continue
        rows.append((tk.replace(".NS", "").replace(".BO", ""), float(mc)))
    rows.sort(key=lambda x: x[1])  # prefer smaller first (your band)
    # prefer mid band if possible
    mid = [s for s, m in rows if 300 <= m <= 8000]
    rest = [s for s, m in rows if s not in mid]
    ordered = mid + rest
    return ordered[:limit]


def resolve_one(client: NSEClient, sym: str) -> dict:
    tried = []
    for fn, name in (
        (lambda: from_nse_pledge_api(client, sym), "nse_pledge_api"),
        (lambda: from_nse_shareholding_master(client, sym), "nse_shp_master"),
        (lambda: from_screener(sym), "screener"),
    ):
        try:
            r = fn()
        except Exception as e:
            r = dict(ok=False, source=name, error=str(e)[:80])
        tried.append(r)
        if r.get("ok") and r.get("pledge") is not None:
            return dict(
                ok=True,
                pledge=float(r["pledge"]),
                pledge_chg=r.get("pledge_chg"),
                as_of=r.get("as_of") or dt.date.today().isoformat(),
                source=r.get("source"),
                tried=tried,
            )
    return dict(ok=False, tried=tried)


def main():
    ap = argparse.ArgumentParser(description="Refresh free pledge cache for daily scanner")
    ap.add_argument("--tickers", default="", help="Comma-separated NSE symbols")
    ap.add_argument("--file", default="", help="Text file, one symbol per line")
    ap.add_argument("--from-fundamentals", action="store_true")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--delay", type=float, default=0.9)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    syms: list[str] = []
    if args.tickers:
        syms.extend(s.strip().upper().replace(".NS", "") for s in args.tickers.split(",") if s.strip())
    if args.file:
        p = Path(args.file)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip().upper().replace(".NS", "")
                if line and not line.startswith("#"):
                    syms.append(line)
    if args.from_fundamentals:
        syms.extend(symbols_from_fundamentals(args.limit))

    # de-dupe preserve order
    seen = set()
    ordered = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            ordered.append(s)

    if not ordered:
        print("No symbols. Use --tickers, --file, or --from-fundamentals")
        sys.exit(1)

    print(f"Refreshing pledge for {len(ordered)} symbols (free sources only)…")
    client = NSEClient(delay=args.delay)
    cache = load_json(PLEDGE_CACHE, {})
    ok_n = fail_n = 0

    for i, sym in enumerate(ordered, 1):
        r = resolve_one(client, sym)
        if r.get("ok"):
            ok_n += 1
            rec = {
                "pledge": r["pledge"],
                "pledge_chg": r.get("pledge_chg"),
                "as_of": r.get("as_of"),
                "source": r.get("source"),
                "updated": dt.date.today().isoformat(),
            }
            print(f"  [{i}/{len(ordered)}] {sym}: {r['pledge']}%  via {r['source']}")
            if not args.dry_run:
                cache[sym] = rec
        else:
            fail_n += 1
            errs = [t.get("error") or ("ok" if t.get("ok") else "fail") for t in r.get("tried") or []]
            prev = from_local_cache(sym)
            keep = f" (kept cache {prev.get('pledge')}%)" if prev.get("ok") else ""
            print(f"  [{i}/{len(ordered)}] {sym}: FAIL {errs}{keep}")
        time.sleep(args.delay)

    if not args.dry_run:
        save_json(PLEDGE_CACHE, cache)
        print(f"\nWrote {PLEDGE_CACHE}  ok={ok_n} fail={fail_n} total_cached={len(cache)}")
        print("Commit data/pledge_cache.json so GitHub Actions can use it.")
    else:
        print(f"\nDry-run only  ok={ok_n} fail={fail_n}")


if __name__ == "__main__":
    main()
