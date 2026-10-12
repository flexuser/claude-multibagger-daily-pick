"""Price / liquidity stage — yfinance bulk download with optional nselib fallback."""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import pandas as pd

from mb.utils import num


def tech_from_series(close: pd.Series, volume: pd.Series) -> Optional[dict]:
    close = close.dropna()
    if len(close) < 130:
        return None
    last = float(close.iloc[-1])
    ma200 = (
        float(close.rolling(200).mean().iloc[-1])
        if len(close) >= 200
        else float(close.mean())
    )
    vol = volume.reindex(close.index).fillna(0)
    v6 = float(vol.tail(126).mean()) or 1.0
    spark = close.tail(250).iloc[:: max(1, len(close.tail(250)) // 120)]
    return dict(
        price=round(last, 2),
        last_date=str(close.index[-1])[:10],
        ret_1y=round((last / float(close.iloc[0]) - 1) * 100, 1),
        ret_6m=round((last / float(close.iloc[-126]) - 1) * 100, 1),
        ret_3m=round((last / float(close.iloc[-63]) - 1) * 100, 1),
        above_200dma=round((last / ma200 - 1) * 100, 1),
        from_52w_high=round((last / float(close.max()) - 1) * 100, 1),
        vol_ratio=round(float(vol.tail(21).mean()) / v6, 2),
        turnover_cr=round(float((close * vol).tail(63).mean()) / 1e7, 2),
        spark=[round(float(x), 2) for x in spark.tolist()],
    )


def fetch_prices(tickers: list[str]) -> tuple[dict[str, dict], Optional[dict]]:
    """Bulk Yahoo download. Returns (prices_by_ticker, nifty_stats)."""
    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    out: dict[str, dict] = {}
    for i in range(0, len(tickers), 80):
        chunk = tickers[i : i + 80]
        try:
            df = yf.download(
                chunk,
                period="1y",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception as e:
            print(f"  price chunk failed: {e}")
            continue
        for tk in chunk:
            try:
                sub = df[tk] if isinstance(df.columns, pd.MultiIndex) else df
                t = tech_from_series(sub["Close"].squeeze(), sub["Volume"].squeeze())
                if t:
                    out[tk] = t
            except Exception:
                pass
        print(f"  prices {min(i + 80, len(tickers))}/{len(tickers)}")
        time.sleep(1)

    missing = [t for t in tickers if t not in out]
    if missing:
        print(
            f"  no usable price history for {len(missing)} of {len(tickers)} tickers "
            f"(delisted, renamed, newly listed or <130 days), e.g. {', '.join(missing[:8])}"
        )

    nifty = None
    try:
        n = yf.download("^NSEI", period="1y", interval="1d", auto_adjust=True, progress=False)
        c = n["Close"].squeeze().dropna()
        nifty = dict(
            last=float(c.iloc[-1]),
            ret_6m=float((c.iloc[-1] / c.iloc[-126] - 1) * 100),
        )
    except Exception as e:
        print(f"  Nifty fetch failed: {e}")
    return out, nifty


def enrich_delivery(prices: dict[str, dict], top_tickers: list[str], delay: float = 0.6) -> None:
    """
    Optional free enrichment via nselib: average delivery % for recent period.
    Fails soft — leaves prices unchanged if nselib is missing or blocked.
    """
    try:
        from nselib import capital_market
    except ImportError:
        print("  nselib not installed; skipping delivery enrichment")
        return

    ok = 0
    for tk in top_tickers[:40]:
        sym = tk.replace(".NS", "").replace(".BO", "")
        try:
            df = capital_market.price_volume_and_deliverable_position_data(
                symbol=sym, period="1M"
            )
            if df is None or df.empty:
                continue
            # Column names vary slightly across nselib versions
            deliv_col = next(
                (c for c in df.columns if "deliv" in c.lower() and "%" in c.lower()),
                None,
            )
            if deliv_col is None:
                deliv_col = next((c for c in df.columns if "deliv" in c.lower()), None)
            if deliv_col is None:
                continue
            series = pd.to_numeric(df[deliv_col], errors="coerce").dropna()
            if len(series) < 5:
                continue
            avg_deliv = float(series.tail(21).mean())
            if tk in prices:
                prices[tk]["delivery_pct"] = round(avg_deliv, 1)
                ok += 1
        except Exception:
            pass
        time.sleep(delay)
    if ok:
        print(f"  delivery % enriched for {ok} tickers via nselib")
