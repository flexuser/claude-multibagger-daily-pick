"""Scoring edge cases. Run: python tests/test_scoring.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mb.scoring import score_pillars, composite, red_flags, eligible, data_suspect, ramp, ramp_inv
from mb.utils import avg, num, clean
import math


def test_ramp():
    assert ramp(None, 0, 10) is None
    assert ramp(0, 0, 10) == 0
    assert ramp(10, 0, 10) == 100
    assert ramp(5, 0, 10) == 50
    assert ramp_inv(0, 0, 10) == 100
    assert ramp_inv(10, 0, 10) == 0


def test_composite_nan_and_partial():
    assert composite({}) is None
    assert composite({"proof": None, "quality": None}) is None
    s = composite({"proof": 80, "quality": float("nan"), "moat": 50})
    assert s is not None and not math.isnan(s)


def test_data_suspect():
    assert data_suspect({"rev_cagr": 200}) is not None
    assert data_suspect({"op_margin": 90}) is not None
    assert data_suspect({"rev_cagr": 25, "op_margin": 15}) is None


def test_eligible_financial_reject():
    m = dict(fin_sector="Banks", rev_cagr=30, op_margin=20, roce=18, mcap_cr=2000,
             fin_date="2026-06-01", de=0.2, dilution=1)
    pil = score_pillars(m)
    ok, why = eligible(m, pil, [])
    assert not ok and "financial" in why


def test_eligible_good():
    m = dict(
        fin_sector="Industrials", sector="Defence",
        rev_cagr=25, q_rev_yoy=30, profit_cagr=28,
        op_margin=16, op_margin_chg=2, roce=20, roce_chg=1,
        de=0.3, dilution=2, insider_pct=55, inst_pct=10, analysts=2,
        fcf_positive=1, cfo_pat=0.9, interest_coverage=12,
        mcap_cr=2000, revenue_cr=800, pe=28, peg=1.1,
        themes=["Defence and aerospace"], moat_kw=2,
        fin_date="2026-06-01", fetched="2026-10-12",
        pledge=2, neg_count=0,
        ret_6m=12, nifty_6m=8, above_200dma=10, from_52w_high=-12, vol_ratio=1.1,
    )
    pil = score_pillars(m)
    fl = red_flags(m)
    ok, why = eligible(m, pil, fl)
    assert ok, why
    assert composite(pil) is not None


def test_clean_json():
    assert clean(float("nan")) is None
    assert clean(float("inf")) is None
    assert clean({"a": float("nan")}) == {"a": None}


if __name__ == "__main__":
    test_ramp()
    test_composite_nan_and_partial()
    test_data_suspect()
    test_eligible_financial_reject()
    test_eligible_good()
    test_clean_json()
    print("test_scoring: OK")
