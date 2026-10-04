"""Run: python -m pytest tests  (or python tests/test_signals.py)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import signals as S

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


def test_insider_net_and_exclusions():
    rows = [
        {"personCategory": "Promoters", "tdpTransactionType": "Buy", "secVal": "25000000", "acqMode": "Market Purchase", "date": "10-Aug-2026"},
        {"personCategory": "Promoters", "tdpTransactionType": "Buy", "secVal": "90000000", "acqMode": "ESOP", "date": "11-Aug-2026"},
        {"personCategory": "Employees", "tdpTransactionType": "Buy", "secVal": "90000000", "acqMode": "Market Purchase", "date": "11-Aug-2026"},
    ]
    net, buys, sells = S.parse_insider(rows, today=T)
    assert abs(net - 2.5) < 1e-9 and buys == 1 and sells == 0


def test_pledge_and_shareholding():
    now, chg = S.parse_pledge([{"percPromoterShares": "12.5", "shp_date": "30-Jun-2026"}, {"percPromoterShares": "4.0", "shp_date": "30-Jun-2025"}])
    assert now == 12.5 and abs(chg - 8.5) < 1e-9
    sh = S.parse_shareholding([{"date": "30-JUN-2026", "pr_and_prgrp": "58.4"}, {"date": "30-SEP-2025", "pr_and_prgrp": "56.1"}])
    assert abs(sh["promoter_chg"] - 2.3) < 1e-9


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
