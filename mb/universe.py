"""NSE small / mid / micro-cap universe loader with fallbacks."""
from __future__ import annotations

import io
import re
import sys

import pandas as pd
import requests

from mb.config import NSE_URLS, UA, UNIVERSE_CSV, ROOT


def load_universe() -> list[str]:
    """
    NSE index constituents. Falls back to the last good download, then to
    universe_extra.txt (one Yahoo ticker per line, e.g. ASTRAMICRO.NS).
    """
    tickers: list[str] = []
    try:
        s = requests.Session()
        s.headers.update({
            "User-Agent": UA,
            "Accept": "text/csv,*/*",
            "Referer": "https://www.nseindia.com/",
        })
        s.get("https://www.nseindia.com", timeout=20)  # cookies NSE expects
        rows = []
        for urls in NSE_URLS:
            text = None
            for url in urls:
                try:
                    r = s.get(url, timeout=30)
                    r.raise_for_status()
                    text = r.text
                    break
                except Exception as e:
                    print(f"  {url.rsplit('/', 1)[-1]} failed from {url.split('/')[2]}: {str(e)[:60]}")
            if text is None:
                raise RuntimeError("both sources failed for one index list")
            df = pd.read_csv(io.StringIO(text))
            df.columns = [c.strip() for c in df.columns]
            for _, row in df.iterrows():
                rows.append({
                    "ticker": str(row["Symbol"]).strip() + ".NS",
                    "name": str(row.get("Company Name", "")).strip(),
                })
        udf = pd.DataFrame(rows).drop_duplicates("ticker")
        udf.to_csv(UNIVERSE_CSV, index=False)
        tickers = udf["ticker"].tolist()
        print(f"Universe: downloaded {len(tickers)} tickers from NSE")
    except Exception as e:
        print(f"NSE download failed ({e}); using cached universe")
        if UNIVERSE_CSV.exists():
            tickers = pd.read_csv(UNIVERSE_CSV)["ticker"].tolist()

    extra = ROOT / "universe_extra.txt"
    if extra.exists():
        tickers += [
            ln.strip()
            for ln in extra.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        ]

    tickers = list(dict.fromkeys(tickers))
    before = len(tickers)
    tickers = [
        t for t in tickers
        if "DUMMY" not in t.upper()
        and re.fullmatch(r"[A-Za-z0-9&\-]+\.(NS|BO)", t.strip())
    ]
    if len(tickers) < before:
        print(f"Universe: dropped {before - len(tickers)} placeholder or invalid symbols")
    if not tickers:
        sys.exit(
            "No universe available. Add tickers to universe_extra.txt "
            "(one per line, e.g. ASTRAMICRO.NS)."
        )
    return tickers
