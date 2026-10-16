"""Validation & price sanity. Run: python tests/test_validate.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from mb.validate import sanitize_metrics, price_series_sanity, safe_div
from mb.diligence import normalize


def test_sanitize_clears_absurd():
    # Extreme but plausible growth is retained and flagged (not erased)
    m = sanitize_metrics(dict(rev_cagr=999, op_margin=15, pe=30, roce=20))
    assert m["rev_cagr"] == 999
    assert m["op_margin"] == 15
    assert "rev_cagr" in (m.get("_sanity_extreme") or [])
    # Truly impossible values outside EXTREME_KEEP still clear
    m2 = sanitize_metrics(dict(op_margin=999, pe=30))
    assert m2["op_margin"] is None
    assert "op_margin" in m2["_sanity_cleared"]


def test_sanitize_nan():
    m = sanitize_metrics(dict(roce=float("nan"), de=0.5))
    assert m["roce"] is None
    assert m["de"] == 0.5


def test_safe_div():
    assert safe_div(10, 0) is None
    assert safe_div(10, 2) == 5.0
    assert safe_div(None, 2) is None


def test_price_sanity_spike():
    idx = pd.date_range("2025-01-01", periods=150, freq="B")
    close = pd.Series(100.0, index=idx)
    close.iloc[-1] = 200.0  # +100% one day
    vol = pd.Series(1e6, index=idx)
    ok, reason = price_series_sanity(close, vol)
    assert not ok and reason and "daily_move" in reason


def test_price_sanity_ok():
    idx = pd.date_range("2025-01-01", periods=150, freq="B")
    close = pd.Series(range(100, 250), index=idx).astype(float)
    vol = pd.Series(1e6, index=idx)
    ok, reason = price_series_sanity(close, vol)
    assert ok


def test_normalize_requires_summary():
    # Empty summary is invalid
    assert normalize({"verdict": "green", "sources": ["https://a.com"]}) is None
    r = normalize({
        "verdict": "green",
        "summary": "A real company that makes widgets for defence and has a clean record.",
        "sources": ["https://example.com/filing"],
        "strengths": ["a"], "risks": ["b"],
    })
    assert r and r["verdict"] == "green"
    assert r.get("management") == "not found"
    assert r.get("_schema") == "diligence_v2"
    # Short summary is allowed (tests and terse models)
    r2 = normalize({"verdict": "yellow", "summary": "ok enough", "sources": []})
    assert r2 and r2["verdict"] == "yellow"


if __name__ == "__main__":
    test_sanitize_clears_absurd()
    test_sanitize_nan()
    test_safe_div()
    test_price_sanity_spike()
    test_price_sanity_ok()
    test_normalize_requires_summary()
    print("test_validate: OK")
