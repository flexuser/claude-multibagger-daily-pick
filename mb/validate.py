"""
Post-ingest validation and price sanity checks.

Goals (residual gaps we harden here):
  * Map non-finite / absurd ratios to None instead of poisoning ranks
  * Flag suspicious one-day price moves (possible bad ticks / unadjusted CA)
  * Keep the daily job alive: never raise on a single bad ticker

This is NOT full point-in-time fundamental history. Live picks still use
the latest Yahoo snapshot; treat any multi-year "backtest" of this scanner
as approximate, not PIT-correct.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from mb.utils import num

# Soft bounds: outside → field cleared (None) so pillars drop it
RATIO_BOUNDS = {
    "rev_cagr": (-50, 150),
    "profit_cagr": (-80, 200),
    "q_rev_yoy": (-80, 300),
    "q_profit_yoy": (-90, 400),
    "op_margin": (-30, 80),
    "op_margin_chg": (-40, 40),
    "q_opm_chg": (-40, 40),
    "roce": (-20, 150),
    "roce_chg": (-50, 50),
    "de": (0, 20),
    "dilution": (-30, 100),
    "pe": (0, 500),
    "peg": (-5, 20),
    "cfo_pat": (-5, 5),
    "interest_coverage": (0, 500),
    "recv_days": (0, 400),
    "recv_days_chg_pct": (-80, 200),
    "insider_pct": (0, 100),
    "inst_pct": (0, 100),
    "pledge": (0, 100),
    "pledge_chg": (-50, 50),
    "promoter_chg": (-30, 30),
    "fii_chg": (-30, 30),
    "dii_chg": (-30, 30),
    "capex_rev_pct": (0, 80),
    "cwip_growth": (-80, 500),
    "gppe_growth": (-80, 300),
    "mcap_cr": (1, 5_000_000),
    "revenue_cr": (0, 5_000_000),
    "rsi_14": (0, 100),
    "delivery_pct": (0, 100),
    "vol_ratio": (0, 20),
    "above_200dma": (-90, 300),
    "from_52w_high": (-95, 5),
    "ret_1y": (-95, 500),
    "ret_6m": (-90, 300),
    "ret_3m": (-80, 200),
    "ret_1m": (-70, 150),
}

# One-day move beyond this (without known split) → quarantine technicals
MAX_ABS_DAILY_RET_PCT = 40.0


def _finite(v: Any) -> Optional[float]:
    n = num(v)
    if n is None:
        return None
    if not math.isfinite(n):
        return None
    return n


def sanitize_metrics(m: dict) -> dict:
    """
    Return a copy with non-finite / out-of-bound numeric fields set to None.
    Adds m['_sanity'] list of cleared field names for debugging.
    """
    out = dict(m)
    cleared = []
    for k, (lo, hi) in RATIO_BOUNDS.items():
        if k not in out:
            continue
        v = _finite(out.get(k))
        if v is None:
            if out.get(k) is not None:
                cleared.append(k)
            out[k] = None
            continue
        if v < lo or v > hi:
            cleared.append(k)
            out[k] = None
        else:
            out[k] = v

    # Booleans / ints that must stay sane
    for k in ("fcf_positive", "trend_structure", "acquisition", "analysts",
              "policy_hits", "moat_kw", "event_score", "neg_count", "neg_events"):
        if k in out and out[k] is not None:
            try:
                if k in ("fcf_positive", "trend_structure", "acquisition"):
                    out[k] = int(bool(out[k])) if k != "acquisition" else out[k]
                elif k == "acquisition":
                    out[k] = bool(out[k]) if isinstance(out[k], (bool, int)) else out[k]
                else:
                    fv = _finite(out[k])
                    out[k] = None if fv is None else fv
            except Exception:
                out[k] = None
                cleared.append(k)

    out["_sanity_cleared"] = cleared
    return out


def price_series_sanity(close, volume) -> tuple[bool, Optional[str]]:
    """
    Check adjusted close series for impossible one-day gaps.
    Returns (ok, reason). ok=False means technical features should be discarded.
    """
    try:
        c = close.dropna()
        if len(c) < 5:
            return False, "too_short"
        rets = c.pct_change().dropna() * 100.0
        if rets.empty:
            return True, None
        worst = float(rets.abs().max())
        if worst > MAX_ABS_DAILY_RET_PCT:
            # Allow if it looks like a single corporate-action day and series
            # continues smoothly after — still quarantine to be safe for momentum.
            return False, f"daily_move_{worst:.0f}pct"
        # Zero/negative prices
        if float(c.min()) <= 0:
            return False, "non_positive_price"
        return True, None
    except Exception as e:
        return False, f"sanity_error:{type(e).__name__}"


def safe_div(a: Any, b: Any) -> Optional[float]:
    """Division that never raises; None on bad inputs."""
    na, nb = _finite(a), _finite(b)
    if na is None or nb is None or nb == 0:
        return None
    r = na / nb
    return r if math.isfinite(r) else None
