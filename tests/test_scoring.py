"""Scoring edge cases. Run: python tests/test_scoring.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mb.scoring import score_pillars, composite, red_flags, eligible, classify, data_suspect, ramp, ramp_inv
from mb.utils import avg, num, clean
import math


def base_ok(**kwargs):
    m = dict(
        fin_sector="Industrials", sector="Defence",
        rev_cagr=25, q_rev_yoy=30, q_profit_yoy=28, profit_cagr=28,
        op_margin=16, op_margin_chg=2, roce=20, roce_chg=1,
        de=0.3, dilution=2, insider_pct=55, inst_pct=10, analysts=2,
        fcf_positive=1, cfo_pat=0.9, interest_coverage=12,
        mcap_cr=2000, revenue_cr=800, pe=18, peg=0.9,
        themes=["Defence and aerospace"], moat_kw=2,
        fin_date="2026-06-01", fetched="2026-10-12",
        pledge=2, neg_count=0,
        ret_6m=12, nifty_6m=8, above_200dma=10, from_52w_high=-12, vol_ratio=1.1,
        recv_days_chg_pct=5,
    )
    m.update(kwargs)
    return m


def test_ramp():
    assert ramp(None, 0, 10) is None
    assert ramp(0, 0, 10) == 0
    assert ramp(10, 0, 10) == 100


def test_composite_requires_all_dimensions():
    assert composite({}) is None
    assert composite({"quality": 80, "growth": 70}) is None
    full = score_pillars(base_ok())
    s = composite(full)
    assert s is not None and not math.isnan(s)


def test_shortlist_ok():
    m = base_ok()
    d = classify(m, red_flags(m))
    assert d["outcome"] == "shortlist", d
    ok, why = eligible(m, score_pillars(m), red_flags(m))
    assert ok, why


def test_missing_quarter_not_shortlist():
    m = base_ok(q_rev_yoy=None)
    d = classify(m, [])
    assert d["outcome"] == "unknown"
    assert any("q_rev_yoy" in x for x in d["unknown"])


def test_extreme_receivables_fail():
    m = base_ok(recv_days_chg_pct=251)
    d = classify(m, red_flags(m))
    assert d["outcome"] == "fail"
    assert any("receivable" in x.lower() for x in d["fail"])


def test_high_pe_fail():
    m = base_ok(pe=116, peg=3.0)
    d = classify(m, [])
    assert d["outcome"] == "fail"


def test_financial_reject():
    m = base_ok(fin_sector="Banks")
    d = classify(m, [])
    assert d["outcome"] == "fail"


def test_manual_exception_stays_watchlist():
    m = base_ok(manual_exception=True, de=0.7)
    d = classify(m, [])
    assert d["outcome"] == "watchlist"
    assert any("manual" in x.lower() for x in d["watch"])


def test_clean_json():
    assert clean(float("nan")) is None


if __name__ == "__main__":
    test_ramp()
    test_composite_requires_all_dimensions()
    test_shortlist_ok()
    test_missing_quarter_not_shortlist()
    test_extreme_receivables_fail()
    test_high_pe_fail()
    test_financial_reject()
    test_manual_exception_stays_watchlist()
    test_clean_json()
    print("test_scoring: OK")
