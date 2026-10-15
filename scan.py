#!/usr/bin/env python3
"""
Daily multibagger scanner + Short-term technical signals — CLI entry point.

  python scan.py --demo                 # synthetic, no network
  python scan.py --max-fetch 50         # real multibagger scan
  python scan.py --short                # short-term / swing signals only
  python scan.py --short --demo         # short-term demo
  python scan.py --check ASTRAMICRO.NS  # single-ticker sanity check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scan.py` from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mb.pipeline import run, run_check, run_short


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Daily NSE multibagger scanner + short-term technical signals (free-tier data)"
    )
    ap.add_argument("--demo", action="store_true", help="synthetic data, no network")
    ap.add_argument("--max-fetch", type=int, default=150, help="max fundamentals refreshed this run")
    ap.add_argument("--delay", type=float, default=0.8, help="seconds between network calls")
    ap.add_argument("--check", metavar="TICKER", help="fetch and print one company's metrics")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument(
        "--short",
        action="store_true",
        help="Run short-term / swing technical scanner (1 day – 2 weeks holding)",
    )
    ap.add_argument(
        "--max-scan",
        type=int,
        default=None,
        help="Max tickers to scan in short-term mode (default from config)",
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="Print near-misses and reject breakdown (short mode)",
    )
    a = ap.parse_args()

    if a.check:
        run_check(a.check)
        return

    if a.short:
        run_short(demo=a.demo, max_scan=a.max_scan, delay=a.delay, no_notify=a.no_notify, debug=a.debug)
        return

    run(demo=a.demo, max_fetch=a.max_fetch, delay=a.delay, no_notify=a.no_notify)


if __name__ == "__main__":
    main()
