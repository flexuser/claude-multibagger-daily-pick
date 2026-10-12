"""Price / liquidity stage — yfinance bulk download with richer technicals + market regime."""
from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
import pandas as pd

from mb.validate import price_series_sanity


def _rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    if len(close) < period + 2:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    avg_loss = float(loss.iloc[-1]) if loss is not None else 0.0
    if avg_loss == 0:
        return 100.0
    rs = float(gain.iloc[-1]) / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def tech_from_series(close: pd.Series, volume: pd.Series) -> Optional[dict]:
    close = close.dropna()
    if len(close) < 130:
        return None
    ok, reason = price_series_sanity(close, volume)
    if not ok:
        return None  # drop series with impossible gaps / bad ticks
    last = float(close.iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else float(close.mean())
    ma200 = (
        float(close.rolling(200).mean().iloc[-1])
        if len(close) >= 200
        else float(close.mean())
    )
    vol = volume.reindex(close.index).fillna(0)
    v6 = float(vol.tail(126).mean()) or 1.0
    spark = close.tail(250).iloc[:: max(1, len(close.tail(250)) // 120)]

    # Max drawdown over available history (approx 1y)
    roll_max = close.cummax()
    dd = (close / roll_max - 1.0) * 100
    max_dd = float(dd.min()) if len(dd) else None

    # 20-day realized vol (annualised-ish, as % move)
    rets = close.pct_change().dropna()
    vol_20d = float(rets.tail(20).std() * np.sqrt(252) * 100) if len(rets) >= 20 else None

    # Higher highs / higher lows structure (last 60 sessions vs prior 60)
    struct = None
    if len(close) >= 120:
        a, b = close.iloc[-120:-60], close.iloc[-60:]
        struct = 1 if (float(b.max()) >= float(a.max()) and float(b.min()) >= float(a.min())) else 0

    return dict(
        price=round(last, 2),
        last_date=str(close.index[-1])[:10],
        ret_1y=round((last / float(close.iloc[0]) - 1) * 100, 1),
        ret_6m=round((last / float(close.iloc[-126]) - 1) * 100, 1),
        ret_3m=round((last / float(close.iloc[-63]) - 1) * 100, 1),
        ret_1m=round((last / float(close.iloc[-21]) - 1) * 100, 1) if len(close) >= 21 else None,
        above_200dma=round((last / ma200 - 1) * 100, 1),
        above_50dma=round((last / ma50 - 1) * 100, 1),
        ma50_vs_200=round((ma50 / ma200 - 1) * 100, 1),  # golden/death cross proxy
        from_52w_high=round((last / float(close.max()) - 1) * 100, 1),
        max_dd_1y=round(max_dd, 1) if max_dd is not None else None,
        rsi_14=_rsi(close),
        vol_20d=round(vol_20d, 1) if vol_20d is not None else None,
        trend_structure=struct,
        vol_ratio=round(float(vol.tail(21).mean()) / v6, 2),
        turnover_cr=round(float((close * vol).tail(63).mean()) / 1e7, 2),
        spark=[round(float(x), 2) for x in spark.tolist()],
    )


def fetch_prices(tickers: list[str]) -> tuple[dict[str, dict], Optional[dict]]:
    """Bulk Yahoo download. Returns (prices_by_ticker, nifty_regime_stats)."""
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

    nifty = _nifty_regime()
    return out, nifty


def _nifty_regime() -> Optional[dict]:
    """Market regime from Nifty: trend, returns, simple risk-on/off."""
    import yfinance as yf

    try:
        n = yf.download("^NSEI", period="1y", interval="1d", auto_adjust=True, progress=False)
        c = n["Close"].squeeze().dropna()
        if len(c) < 130:
            return None
        last = float(c.iloc[-1])
        ma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else float(c.mean())
        ma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else float(c.mean())
        ret_6m = float((last / float(c.iloc[-126]) - 1) * 100)
        ret_3m = float((last / float(c.iloc[-63]) - 1) * 100)
        ret_1m = float((last / float(c.iloc[-21]) - 1) * 100)
        above_200 = (last / ma200 - 1) * 100
        # Simple regime: risk_on if above 200dma and 3m not deeply negative
        if above_200 > 0 and ret_3m > -5:
            regime = "risk_on"
        elif above_200 < -3 or ret_3m < -10:
            regime = "risk_off"
        else:
            regime = "neutral"
        return dict(
            last=last,
            ret_6m=ret_6m,
            ret_3m=ret_3m,
            ret_1m=ret_1m,
            above_200dma=round(above_200, 1),
            ma50_vs_200=round((ma50 / ma200 - 1) * 100, 1),
            regime=regime,
        )
    except Exception as e:
        print(f"  Nifty fetch failed: {e}")
        return None


def enrich_delivery(prices: dict[str, dict], top_tickers: list[str], delay: float = 0.6) -> None:
    """Optional free enrichment via nselib: average delivery %."""
    try:
        from nselib import capital_market
    except ImportError:
        print("  nselib not installed; skipping delivery enrichment")
        return

    ok = 0
    for tk in top_tickers[:40]:
        sym = tk.replace(".NS", "").replace(".BO", "")
        try:
            df = capital_market.price_volume_and_deliverable_position_data(symbol=sym, period="1M")
            if df is None or df.empty:
                continue
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
