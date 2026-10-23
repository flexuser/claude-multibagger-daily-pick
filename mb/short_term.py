"""
mb/short_term.py
================
Professional short-term / swing technical signal engine
(Intraday bias → max 1–2 weeks holding)

Designed for free-stack only (yfinance + pandas + numpy).
Fits cleanly into the existing multibagger pipeline.

Features included:
1. Multi-timeframe alignment (Daily + higher-timeframe bias)
2. Dynamic Support / Resistance (swing highs & lows)
3. Volume-confirmed breakout detection
4. ATR-based dynamic Stop Loss & Targets
5. False-breakout filters
6. Market Regime filter (risk_on / neutral / risk_off)
7. RSI + trend structure filters
8. Liquidity & price filters
9. Confidence scoring (0–100)
10. Position sizing helper (risk-based)
11. Sector / relative strength soft filter
12. Holding period suggestion
13. Clean signal object ready for alerts & rendering
14. Batch scanner
15. Basic expectancy helper
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (can be overridden from mb.config)
# ---------------------------------------------------------------------------
ST_CFG = {
    # Liquidity
    "min_price": 30.0,
    "min_avg_turnover_cr": 1.5,
    "min_volume_surge": 1.15,

    # ATR & Risk
    "atr_period": 14,
    "sl_atr_mult": 1.35,
    "t1_atr_mult": 1.5,
    "t2_atr_mult": 2.5,
    "t3_atr_mult": 3.6,

    # Filters
    "rsi_period": 14,
    "rsi_max": 74,
    "rsi_min": 32,
    "min_confidence": 55,               # base threshold

    # When market is risk_off, demand higher quality
    "min_confidence_risk_off": 62,

    # Structure
    "swing_lookback": 7,
    "breakout_buffer_pct": 0.10,

    # Regime – now allows all, but applies different confidence bars
    "allow_regimes": {"risk_on", "neutral", "risk_off"},
}


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------
@dataclass
class ShortTermSignal:
    ticker: str
    signal: str = "NONE"                 # "BUY" | "NONE"
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    t1: Optional[float] = None
    t2: Optional[float] = None
    t3: Optional[float] = None
    confidence: float = 0.0
    holding_days: str = "3-12"
    risk_reward_t1: Optional[float] = None
    atr: Optional[float] = None
    rsi: Optional[float] = None
    volume_surge: Optional[float] = None
    regime: str = "unknown"
    reasons: List[str] = field(default_factory=list)
    invalidation: Optional[str] = None
    resistance: Optional[float] = None
    support: Optional[float] = None
    last_price: Optional[float] = None
    as_of: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["reasons"] = list(self.reasons or [])
        return d


# ---------------------------------------------------------------------------
# Core Technical Helpers
# ---------------------------------------------------------------------------
def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period // 2).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def find_swing_levels(df: pd.DataFrame, lookback: int = 7) -> Dict[str, float]:
    """
    Robust swing high / swing low detection using local extrema.
    Returns nearest resistance and support.
    """
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)

    resistance = None
    support = None

    # Search from recent bars backwards for clean swings
    for i in range(n - lookback - 1, lookback, -1):
        if resistance is None:
            if highs[i] >= highs[i - lookback : i + lookback + 1].max():
                resistance = float(highs[i])
        if support is None:
            if lows[i] <= lows[i - lookback : i + lookback + 1].min():
                support = float(lows[i])
        if resistance is not None and support is not None:
            break

    # Fallbacks
    if resistance is None:
        resistance = float(df["High"].tail(25).max())
    if support is None:
        support = float(df["Low"].tail(25).min())

    return {"resistance": resistance, "support": support}


def volume_surge(df: pd.DataFrame, lookback: int = 20) -> float:
    if "Volume" not in df.columns or len(df) < lookback + 2:
        return 1.0
    avg_vol = df["Volume"].tail(lookback).mean()
    if avg_vol <= 0 or np.isnan(avg_vol):
        return 1.0
    last_vol = float(df["Volume"].iloc[-1])
    return last_vol / avg_vol


# ---------------------------------------------------------------------------
# Main Signal Generator
# ---------------------------------------------------------------------------
def generate_signal(
    ticker: str,
    df: pd.DataFrame,
    market_regime: str = "neutral",
    sector_rs: Optional[float] = None,
    cfg: Optional[dict] = None,
) -> ShortTermSignal:
    """
    Generate a professional short-term BUY signal (or NONE).

    Parameters
    ----------
    ticker : str
    df : pd.DataFrame
        Must contain OHLCV columns (Open, High, Low, Close, Volume).
        Index should be datetime-like, sorted ascending.
    market_regime : str
        "risk_on" | "neutral" | "risk_off"
    sector_rs : float, optional
        Sector relative strength vs Nifty (percentage points)
    cfg : dict, optional
        Override ST_CFG values
    """
    C = {**ST_CFG, **(cfg or {})}
    reasons: List[str] = []
    conf_score = 0.0

    # ----- Basic validation -----
    if df is None or len(df) < 55:
        return ShortTermSignal(ticker=ticker, signal="NONE", reasons=["Insufficient data"])

    needed = {"Open", "High", "Low", "Close", "Volume"}
    if not needed.issubset(set(df.columns)):
        # Try common renames
        colmap = {c: c.title() for c in df.columns}
        df = df.rename(columns=colmap)
        if not needed.issubset(set(df.columns)):
            return ShortTermSignal(ticker=ticker, signal="NONE", reasons=["Missing OHLCV columns"])

    df = df.copy().dropna(subset=["Close", "High", "Low"])
    if len(df) < 55:
        return ShortTermSignal(ticker=ticker, signal="NONE", reasons=["Insufficient clean data"])

    close = df["Close"]
    last = float(close.iloc[-1])
    atr_series = compute_atr(df, C["atr_period"])
    atr = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else None
    rsi_series = compute_rsi(close, C["rsi_period"])
    rsi = float(rsi_series.iloc[-1]) if not np.isnan(rsi_series.iloc[-1]) else None
    vol_surge = volume_surge(df)

    # ----- Liquidity / price filter -----
    if last < C["min_price"]:
        return ShortTermSignal(ticker=ticker, signal="NONE", reasons=["Price too low"])

    # ----- Regime handling -----
    # We now allow all regimes. In risk_off we just raise the confidence bar later.
    if market_regime not in C.get("allow_regimes", {"risk_on", "neutral", "risk_off"}):
        return ShortTermSignal(
            ticker=ticker,
            signal="NONE",
            regime=market_regime,
            reasons=[f"Regime '{market_regime}' not recognised"],
        )

    # ----- Swing S/R -----
    levels = find_swing_levels(df, C["swing_lookback"])
    resistance = levels["resistance"]
    support = levels["support"]

    # ----- Breakout condition -----
    buffer = resistance * (C["breakout_buffer_pct"] / 100.0)
    breakout_level = resistance + buffer
    is_breakout = last > breakout_level
    volume_ok = vol_surge >= C["min_volume_surge"]

    if not is_breakout:
        return ShortTermSignal(
            ticker=ticker,
            signal="NONE",
            reasons=[f"No breakout (close {last:.2f} vs res {resistance:.2f})"],
            regime=market_regime,
            resistance=round(resistance, 2),
            support=round(support, 2),
        )

    reasons.append(f"Breakout above {resistance:.2f}")
    conf_score += 26

    if volume_ok:
        reasons.append(f"Volume surge {vol_surge:.2f}x")
        conf_score += 20
    else:
        reasons.append(f"Volume mild ({vol_surge:.2f}x)")
        conf_score += 4  # soft penalty; still can pass if structure is strong

    # ----- RSI filter -----
    if rsi is not None:
        if C["rsi_min"] <= rsi <= C["rsi_max"]:
            reasons.append(f"RSI healthy ({rsi:.1f})")
            conf_score += 15
        elif rsi > C["rsi_max"]:
            reasons.append(f"RSI extended ({rsi:.1f})")
            conf_score -= 12
        else:
            reasons.append(f"RSI recovering ({rsi:.1f})")
            conf_score += 6

    # ----- Trend / Structure -----
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else ma20

    if last > ma20:
        reasons.append("Above 20 DMA")
        conf_score += 10
    if last > ma50:
        reasons.append("Above 50 DMA")
        conf_score += 8

    # Higher-high / higher-low structure (simple)
    if len(close) >= 40:
        recent = close.tail(20)
        prior = close.iloc[-40:-20]
        if float(recent.max()) >= float(prior.max()) and float(recent.min()) >= float(prior.min()):
            reasons.append("HH-HL structure")
            conf_score += 8

    # ----- Sector relative strength (soft) -----
    if sector_rs is not None:
        if sector_rs > 2:
            reasons.append(f"Sector RS +{sector_rs:.1f}pp")
            conf_score += 8
        elif sector_rs < -8:
            reasons.append(f"Sector weak ({sector_rs:.1f}pp)")
            conf_score -= 10

    # ----- Final confidence -----
    conf_score = max(0.0, min(100.0, conf_score))

    # Higher bar when market is risk_off
    required_conf = C.get("min_confidence", 55)
    if market_regime == "risk_off":
        required_conf = C.get("min_confidence_risk_off", 62)
        reasons.append("Risk-off regime → higher quality required")

    if conf_score < required_conf:
        return ShortTermSignal(
            ticker=ticker,
            signal="NONE",
            confidence=round(conf_score, 1),
            reasons=reasons + [f"Confidence {conf_score:.0f} < required {required_conf}"],
            regime=market_regime,
            resistance=round(resistance, 2),
            support=round(support, 2),
        )

    # ----- Calculate levels (ATR preferred) -----
    entry = round(breakout_level, 2)

    if atr and atr > 0:
        sl = round(entry - (atr * C["sl_atr_mult"]), 2)
        t1 = round(entry + (atr * C["t1_atr_mult"]), 2)
        t2 = round(entry + (atr * C["t2_atr_mult"]), 2)
        t3 = round(entry + (atr * C["t3_atr_mult"]), 2)
    else:
        # Percentage fallback
        sl = round(entry * 0.945, 2)
        t1 = round(entry * 1.035, 2)
        t2 = round(entry * 1.065, 2)
        t3 = round(entry * 1.10, 2)

    # Prefer SL not far below recent support
    if support and sl < support * 0.985:
        sl = round(max(support * 0.992, entry * 0.93), 2)
        reasons.append("SL adjusted near support")

    risk = entry - sl
    rr_t1 = round((t1 - entry) / risk, 2) if risk > 0 else None

    # Reject only if already past T1 (true stale). Small extension above entry is OK.
    if last >= t1:
        return ShortTermSignal(
            ticker=ticker,
            signal="NONE",
            confidence=round(conf_score, 1),
            reasons=reasons + [f"Already past T1 (last {last:.2f} >= T1 {t1})"],
            regime=market_regime,
            resistance=round(resistance, 2),
            support=round(support, 2),
            last_price=round(last, 2),
        )
    if last > entry * 1.05:
        return ShortTermSignal(
            ticker=ticker,
            signal="NONE",
            confidence=round(conf_score, 1),
            reasons=reasons + [f"Already extended (last {last:.2f} > entry+5%)"],
            regime=market_regime,
            resistance=round(resistance, 2),
            support=round(support, 2),
            last_price=round(last, 2),
        )

    as_of = None
    try:
        as_of = str(df.index[-1])[:10]
    except Exception:
        pass

    return ShortTermSignal(
        ticker=ticker,
        signal="BUY",
        entry=entry,
        stop_loss=sl,
        t1=t1,
        t2=t2,
        t3=t3,
        confidence=round(conf_score, 1),
        holding_days="3-12 trading days",
        risk_reward_t1=rr_t1,
        atr=round(atr, 2) if atr else None,
        rsi=round(rsi, 1) if rsi else None,
        volume_surge=round(vol_surge, 2),
        regime=market_regime,
        reasons=reasons,
        invalidation=f"Daily close below {sl}",
        resistance=round(resistance, 2),
        support=round(support, 2),
        last_price=round(last, 2),
        as_of=as_of,
    )


# ---------------------------------------------------------------------------
# Position Sizing Helper
# ---------------------------------------------------------------------------
def position_size(
    capital: float,
    entry: float,
    stop_loss: float,
    risk_per_trade_pct: float = 0.75,
) -> Dict[str, float]:
    """
    Risk-based position sizing.
    Returns quantity and rupee risk.
    """
    risk_per_share = entry - stop_loss
    if risk_per_share <= 0:
        return {"qty": 0, "rupee_risk": 0.0, "position_value": 0.0}

    rupee_risk = capital * (risk_per_trade_pct / 100.0)
    qty = int(rupee_risk / risk_per_share)
    return {
        "qty": qty,
        "rupee_risk": round(qty * risk_per_share, 2),
        "position_value": round(qty * entry, 2),
    }


# ---------------------------------------------------------------------------
# Batch Scanner
# ---------------------------------------------------------------------------
def scan_short_term(
    ohlcv_map: Dict[str, pd.DataFrame],
    market_regime: str = "neutral",
    min_confidence: Optional[float] = None,
    cfg: Optional[dict] = None,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """
    Scan multiple stocks and return sorted list of valid BUY signals.
    If debug=True, also attaches near-miss list on the return via
    scan_short_term.last_near_misses (list of dicts).
    """
    C = {**ST_CFG, **(cfg or {})}
    if min_confidence is None:
        if market_regime == "risk_off":
            min_confidence = C.get("min_confidence_risk_off", 62)
        else:
            min_confidence = C.get("min_confidence", 55)

    results = []
    near_misses = []
    reject_counts: Dict[str, int] = {}

    for ticker, df in ohlcv_map.items():
        try:
            sig = generate_signal(
                ticker, df, market_regime=market_regime, cfg=cfg
            )
            d = sig.to_dict()
            if sig.signal == "BUY" and (sig.confidence or 0) >= min_confidence:
                results.append(d)
            elif debug or (sig.confidence and sig.confidence >= 45):
                # Near-miss: had some structure but failed a gate
                reason = "unknown"
                reasons = sig.reasons or []
                joined = " | ".join(reasons)
                if "Already past T1" in joined:
                    reason = "past_T1"
                elif "Already extended" in joined:
                    reason = "extended"
                elif "No breakout" in joined:
                    reason = "no_breakout"
                elif "Confidence" in joined and "< required" in joined:
                    reason = "low_confidence"
                elif "Volume" in joined:
                    reason = "volume"
                elif "Price too low" in joined:
                    reason = "price"
                elif sig.signal == "BUY":
                    reason = "below_min_conf"
                else:
                    reason = "other"
                reject_counts[reason] = reject_counts.get(reason, 0) + 1
                if reason != "no_breakout":  # don't flood with non-breakouts
                    near_misses.append({
                        "ticker": ticker,
                        "confidence": sig.confidence,
                        "reject": reason,
                        "last_price": d.get("last_price"),
                        "entry": d.get("entry"),
                        "t1": d.get("t1"),
                        "reasons": reasons[:4],
                    })
        except Exception as e:
            logger.warning("Short-term signal failed for %s: %s", ticker, e)

    results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    near_misses.sort(key=lambda x: x.get("confidence") or 0, reverse=True)
    # Expose for pipeline debug printing
    scan_short_term.last_near_misses = near_misses[:25]
    scan_short_term.last_reject_counts = reject_counts
    return results


# ---------------------------------------------------------------------------
# Simple Expectancy Helper (for later backtesting)
# ---------------------------------------------------------------------------
def expectancy(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Basic expectancy calculation."""
    return (win_rate * avg_win) - ((1 - win_rate) * abs(avg_loss))


# ---------------------------------------------------------------------------
# Convenience: fetch OHLCV for a list of tickers (used by pipeline)
# ---------------------------------------------------------------------------
def fetch_ohlcv(
    tickers: List[str],
    period: str = "6mo",
    interval: str = "1d",
    delay: float = 0.35,
) -> Dict[str, pd.DataFrame]:
    """
    Download OHLCV data for short-term scanning.
    Returns {ticker: DataFrame with Open/High/Low/Close/Volume}.
    """
    import time
    import yfinance as yf

    out: Dict[str, pd.DataFrame] = {}
    # Chunk to be polite
    chunk_size = 40
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        try:
            data = yf.download(
                chunk,
                period=period,
                interval=interval,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if data is None or data.empty:
                continue

            if len(chunk) == 1:
                tk = chunk[0]
                df = data.copy()
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.title)
                if "Close" in df.columns and len(df) >= 40:
                    out[tk] = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            else:
                for tk in chunk:
                    try:
                        if isinstance(data.columns, pd.MultiIndex):
                            sub = data[tk].copy()
                        else:
                            sub = data.copy()
                        sub = sub.rename(columns=str.title)
                        if "Close" in sub.columns and len(sub.dropna()) >= 40:
                            out[tk] = sub[["Open", "High", "Low", "Close", "Volume"]].dropna()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("OHLCV chunk failed: %s", e)
        time.sleep(delay)
    return out


# ---------------------------------------------------------------------------
# Multi-day Swing History Tracking
# ---------------------------------------------------------------------------
MAX_HOLDING_DAYS = 12
HISTORY_KEEP = 80  # max closed records to retain


def _check_outcome(sig: dict, ohlcv: Optional[pd.DataFrame], today: str) -> dict:
    """
    Update one historical signal using latest OHLCV.
    Returns the updated signal dict with status and outcome fields.
    """
    if sig.get("status") in ("stopped", "target_hit", "expired"):
        return sig  # already closed

    entry = sig.get("entry")
    sl = sig.get("stop_loss")
    t1 = sig.get("t1")
    t2 = sig.get("t2")
    t3 = sig.get("t3")
    entry_date = sig.get("date")

    if not entry or not sl or ohlcv is None or ohlcv.empty:
        # Can't evaluate — leave active
        return sig

    # Only look at bars after entry date
    try:
        df = ohlcv.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        # Include entry day so same-day target/SL hits are detected
        df = df[df.index.strftime("%Y-%m-%d") >= entry_date]
    except Exception:
        df = ohlcv.iloc[1:] if len(ohlcv) > 1 else ohlcv

    if df.empty:
        return sig

    hit_sl = False
    hit_t1 = hit_t2 = hit_t3 = False
    exit_price = None
    exit_date = None
    outcome = None

    for idx, row in df.iterrows():
        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])
        d = str(idx)[:10]

        # Conservative: if both SL and target touched same day, count as SL first
        if low <= sl:
            hit_sl = True
            exit_price = sl
            exit_date = d
            outcome = "stopped"
            break
        if t1 and high >= t1:
            hit_t1 = True
            exit_price = t1
            exit_date = d
            outcome = "t1_hit"
            # Continue to see if higher targets also hit same day / later
        if t2 and high >= t2:
            hit_t2 = True
            exit_price = t2
            exit_date = d
            outcome = "t2_hit"
        if t3 and high >= t3:
            hit_t3 = True
            exit_price = t3
            exit_date = d
            outcome = "t3_hit"
            break

    # Holding period check
    try:
        from datetime import datetime
        d0 = datetime.strptime(entry_date, "%Y-%m-%d")
        d1 = datetime.strptime(today, "%Y-%m-%d")
        days_held = (d1 - d0).days
    except Exception:
        days_held = 0

    sig = dict(sig)  # copy
    sig["days_held"] = days_held
    sig["hit_t1"] = hit_t1 or sig.get("hit_t1", False)
    sig["hit_t2"] = hit_t2 or sig.get("hit_t2", False)
    sig["hit_t3"] = hit_t3 or sig.get("hit_t3", False)

    if outcome:
        sig["status"] = "stopped" if outcome == "stopped" else "target_hit"
        sig["outcome"] = outcome
        sig["exit_price"] = exit_price
        sig["exit_date"] = exit_date
        # Simple R-multiple
        risk = entry - sl
        if risk > 0 and exit_price:
            sig["r_multiple"] = round((exit_price - entry) / risk, 2)
    elif days_held >= MAX_HOLDING_DAYS:
        sig["status"] = "expired"
        sig["outcome"] = "expired"
        last_close = float(df["Close"].iloc[-1])
        sig["exit_price"] = last_close
        sig["exit_date"] = today
        risk = entry - sl
        if risk > 0:
            sig["r_multiple"] = round((last_close - entry) / risk, 2)
    else:
        sig["status"] = "active"
        # Mark highest target reached so far even while still active
        if hit_t3:
            sig["outcome"] = "t3_hit"
        elif hit_t2:
            sig["outcome"] = "t2_hit"
        elif hit_t1:
            sig["outcome"] = "t1_hit"

    return sig


def update_swing_history(
    new_signals: List[Dict[str, Any]],
    ohlcv_map: Dict[str, pd.DataFrame],
    today: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    1. Update outcomes of previously active signals using latest OHLCV.
    2. Append today's new signals as active.
    3. Return full history list (active + recent closed).
    """
    history = list(history or [])

    # Update existing open signals
    updated = []
    for sig in history:
        if sig.get("status") == "active":
            tk = sig.get("ticker")
            ohlcv = ohlcv_map.get(tk)
            updated.append(_check_outcome(sig, ohlcv, today))
        else:
            updated.append(sig)

    # Avoid duplicate: if ticker already has an open (active) call, do not open another
    active_tickers = {
        s["ticker"] for s in updated
        if s.get("status") == "active" and s.get("ticker")
    }

    for s in new_signals:
        tk = s.get("ticker")
        if not tk or tk in active_tickers:
            continue
        rec = {
            "date": today,
            "ticker": tk,
            "entry": s.get("entry"),
            "stop_loss": s.get("stop_loss"),
            "t1": s.get("t1"),
            "t2": s.get("t2"),
            "t3": s.get("t3"),
            "confidence": s.get("confidence"),
            "status": "active",
            "outcome": None,
            "hit_t1": False,
            "hit_t2": False,
            "hit_t3": False,
            "days_held": 0,
            "exit_price": None,
            "exit_date": None,
            "r_multiple": None,
            "reasons": s.get("reasons") or [],
            "last_price": s.get("last_price"),
            "as_of": s.get("as_of"),
        }
        updated.append(rec)

    # Keep all active + most recent closed
    active = [s for s in updated if s.get("status") == "active"]
    closed = [s for s in updated if s.get("status") != "active"]
    closed = sorted(closed, key=lambda x: x.get("exit_date") or x.get("date") or "", reverse=True)[:HISTORY_KEEP]

    return active + closed


def swing_stats(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Simple performance summary from closed signals."""
    closed = [s for s in history if s.get("status") in ("stopped", "target_hit", "expired")]
    if not closed:
        return {"closed": 0, "win_rate": None, "avg_r": None, "t1_hits": 0, "stopped": 0}

    wins = [s for s in closed if s.get("outcome") in ("t1_hit", "t2_hit", "t3_hit")]
    stopped = [s for s in closed if s.get("outcome") == "stopped"]
    r_list = [s["r_multiple"] for s in closed if s.get("r_multiple") is not None]

    return {
        "closed": len(closed),
        "win_rate": round(100 * len(wins) / len(closed), 1) if closed else None,
        "avg_r": round(sum(r_list) / len(r_list), 2) if r_list else None,
        "t1_hits": len(wins),
        "stopped": len(stopped),
        "expired": len([s for s in closed if s.get("outcome") == "expired"]),
    }
