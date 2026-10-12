"""Run: python tests/test_signals.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from mb import signals as S

T = pd.Timestamp("2026-10-04")


def test_iso_and_nse_dates():
    assert str(S._date("2026-08-11 10:00:00").date()) == "2026-08-11"
    assert str(S._date("20-Sep-2026 17:45:12").date()) == "2026-09-20"


def test_classification():
    assert "order_win" in S.classify_announcement("Bagging/Receiving of orders/contracts", "export order worth Rs 120 crore")
    assert "export" in S.classify_announcement("", "export order from US customer")
    assert "promoter_warrants" not in S.classify_announcement("", "warrants to FPI investor")
    assert "promoter_warrants" in S.classify_announcement("", "warrants to promoter group")
    assert "rating_up" not in S.classify_announcement("", "software upgrade completed")
    assert "pledge_invoked" in S.classify_announcement("", "invocation of pledged shares")


def test_negative_penalty():
    ev = [dict(cats=["order_win"]), dict(cats=["pledge_invoked"])]
    score, counts, neg = S.score_events(ev)
    assert neg == 1 and score == 0


def test_capacity_double():
    assert "capacity_double" in S.classify_announcement("", "company is doubling its capacity at the new plant")


if __name__ == "__main__":
    test_iso_and_nse_dates()
    test_classification()
    test_negative_penalty()
    test_capacity_double()
    print("test_signals: OK")
