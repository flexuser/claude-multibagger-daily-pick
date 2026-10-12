#!/usr/bin/env python3
"""
Daily multibagger scanner — CLI entry point.

  python scan.py --demo                 # synthetic, no network
  python scan.py --max-fetch 50         # real data
  python scan.py --check ASTRAMICRO.NS  # single-ticker sanity check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scan.py` from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mb.pipeline import run, run_check


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily NSE multibagger scanner (free-tier data)")
    ap.add_argument("--demo", action="store_true", help="synthetic data, no network")
    ap.add_argument("--max-fetch", type=int, default=150, help="max fundamentals refreshed this run")
    ap.add_argument("--delay", type=float, default=0.8, help="seconds between network calls")
    ap.add_argument("--check", metavar="TICKER", help="fetch and print one company's metrics")
    ap.add_argument("--no-notify", action="store_true")
    a = ap.parse_args()

    if a.check:
        run_check(a.check)
        return

    run(demo=a.demo, max_fetch=a.max_fetch, delay=a.delay, no_notify=a.no_notify)


if __name__ == "__main__":
    main()
