"""Basic tests for the short-term technical engine."""
import numpy as np
import pandas as pd
from mb.short_term import generate_signal, compute_atr, find_swing_levels, position_size


def _make_df(n=120, breakout=True):
    """Create synthetic OHLCV that optionally breaks out."""
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0.15, 1.2, n))
    if breakout:
        close[-5:] += 8  # force a breakout
    high = close + rng.uniform(0.3, 1.8, n)
    low = close - rng.uniform(0.3, 1.8, n)
    open_ = close + rng.normal(0, 0.4, n)
    vol = rng.integers(200_000, 900_000, n).astype(float)
    vol[-1] *= 2.2  # volume surge
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


def test_atr():
    df = _make_df()
    atr = compute_atr(df)
    assert len(atr) == len(df)
    assert atr.iloc[-1] > 0


def test_swing_levels():
    df = _make_df()
    levels = find_swing_levels(df)
    assert "resistance" in levels and "support" in levels
    assert levels["resistance"] >= levels["support"]


def test_generate_buy():
    df = _make_df(breakout=True)
    sig = generate_signal("TEST.NS", df, market_regime="risk_on")
    assert sig.signal in ("BUY", "NONE")
    if sig.signal == "BUY":
        assert sig.entry is not None
        assert sig.stop_loss < sig.entry
        assert sig.t1 > sig.entry
        assert sig.confidence >= 50


def test_position_size():
    ps = position_size(capital=500_000, entry=300, stop_loss=280, risk_per_trade_pct=0.8)
    assert ps["qty"] > 0
    assert ps["rupee_risk"] > 0


if __name__ == "__main__":
    test_atr()
    test_swing_levels()
    test_generate_buy()
    test_position_size()
    print("All short-term tests passed")
