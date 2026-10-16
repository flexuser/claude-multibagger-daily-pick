
"""
Research-shortlist scoring and classification (Phase 1).

Outcomes:
  fail      — verified disqualifier; never ranked
  unknown   — critical field missing/stale/untrusted; never ranked
  watchlist — may qualify later; ranked only as research backlog
  shortlist — all mandatory gates pass (NOT a buy call)

Thresholds are research-policy hypotheses until Phase 2 validation.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from mb.config import CFG, GATES, WEIGHTS
from mb.utils import avg, ramp, ramp_inv


# Mandatory for Research shortlist. Advisory fields must not fill these holes.
CRITICAL_FIELDS = (
    "rev_cagr",          # multi-year sales growth
    "q_rev_yoy",         # recent same-quarter YoY revenue
    "q_profit_yoy",      # recent profit evidence (proxy for OP until explicit OP field)
    "roce",
    "cfo_pat",
    "de",
    "insider_pct",       # promoter holding
    "dilution",
    "pe",
    "mcap_cr",
)
# pledge often only from NSE signals — missing means cannot shortlist (watchlist), not data error

# Source trust: until filing parsers exist, free vendors are unverified.
# Critical gates cannot PASS shortlist on a single unverified vendor alone
# without explicit source_ok flag — but for Phase 1 practicality we tag
# source and require presence; mark evidence_grade down if unverified.


def trend_score(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    if x < 0:
        return ramp(x, -30, 0) * 0.6
    if x <= 40:
        return 60 + x / 40 * 40
    return max(40, 100 - (x - 40) * 1.5)


def icr_score(m: dict) -> Optional[float]:
    if m.get("interest_coverage") is None:
        return 100.0 if (m.get("de") is not None and m["de"] < 0.05) else None
    return ramp(m["interest_coverage"], 2, 10)


def data_suspect(m: dict) -> Optional[str]:
    if (m.get("rev_cagr") or 0) > 200 or (m.get("q_rev_yoy") or 0) > 400:
        return "revenue growth looks like a data error"
    if (m.get("op_margin") or 0) > 80 or (m.get("roce") or 0) > 150:
        return "margin or ROCE looks like a data error"
    return None


def stale_reason(m: dict) -> Optional[str]:
    d = m.get("fin_date")
    if d:
        try:
            if (dt.date.today() - dt.date.fromisoformat(d)).days > CFG["stale_annual_days"]:
                return f"latest annual results are dated {d}"
        except ValueError:
            pass
    return None


def evidence_coverage(m: dict) -> float:
    present = sum(1 for k in CRITICAL_FIELDS if m.get(k) is not None)
    return present / max(1, len(CRITICAL_FIELDS))


def score_pillars(m: dict) -> dict[str, Optional[float]]:
    """Five independent dimensions. Each metric used once. No keywords/capex/events."""
    rs = None
    if m.get("ret_6m") is not None and m.get("nifty_6m") is not None:
        rs = m["ret_6m"] - m["nifty_6m"]
    m["rs_6m"] = rs

    accel = None
    if m.get("q_rev_yoy") is not None and m.get("rev_cagr") is not None:
        accel = m["q_rev_yoy"] - m["rev_cagr"]
    m["q_accel"] = accel

    return dict(
        quality=ramp(m.get("roce"), 12, 30),
        growth=avg([
            ramp(m.get("rev_cagr"), 12, 35),
            ramp(m.get("q_rev_yoy"), 8, 40),
            ramp(m.get("q_profit_yoy"), 0, 45),
        ]),
        cash=avg([
            ramp(m.get("cfo_pat"), 0.5, 1.2),
            ramp_inv(m.get("de"), 0, 0.8),
            ramp_inv(m.get("recv_days_chg_pct"), 0, 60),
            icr_score(m),
        ]),
        price=avg([
            ramp_inv(m.get("pe"), 8, 25),
            ramp_inv(m.get("peg"), 0.4, 1.2) if m.get("peg") is not None else ramp_inv(m.get("pe"), 8, 25),
        ]),
        discovery=avg([
            ramp_inv(m.get("mcap_cr"), 800, 8000),
            ramp_inv(m.get("inst_pct"), 5, 40) if m.get("inst_pct") is not None else ramp_inv(m.get("mcap_cr"), 800, 8000),
        ]),
    )


def composite(p: dict) -> Optional[float]:
    """No hidden reweighting: every WEIGHTS key must be a finite number."""
    num_, den = 0.0, 0.0
    for k, w in WEIGHTS.items():
        v = p.get(k)
        if v is None:
            return None
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        if fv != fv:
            return None
        num_ += fv * w
        den += w
    if not den:
        return None
    out = num_ / den
    return None if out != out else out


def red_flags(m: dict) -> list[dict]:
    f: list[dict] = []

    def add(sev: str, t: str) -> None:
        f.append(dict(sev=sev, text=t))

    if m.get("dilution") is not None and m["dilution"] > 8:
        add("high", f"Share count up {m['dilution']:.0f}% in ~3 years (dilution).")
    if m.get("de") is not None and m["de"] > 1.0:
        add("high", f"Debt/equity {m['de']:.1f}: a growth miss gets expensive.")
    if (m.get("peg") is not None and m["peg"] > 2.5) or (
        m.get("pe") and m["pe"] > 70 and (m.get("profit_cagr") or 0) < 25
    ):
        add("high", "Valuation already prices in years of success.")
    if m.get("op_margin_chg") is not None and m["op_margin_chg"] < -1.5 and (m.get("rev_cagr") or 0) > 12:
        add("med", "Sales growing but margins shrinking.")
    if m.get("fcf_positive") == 0:
        add("med", "Free cash flow negative: growth may need outside funding.")
    if m.get("roce") is not None and m["roce"] < 10:
        add("med", f"ROCE only {m['roce']:.0f}%.")
    if m.get("inst_pct") is not None and m["inst_pct"] > 40:
        add("med", f"Institutions already hold {m['inst_pct']:.0f}%: less discovery upside.")
    if m.get("insider_pct") is not None and m["insider_pct"] < 30:
        add("med", f"Promoter holding only {m['insider_pct']:.0f}%.")
    if m.get("above_200dma") is not None and m["above_200dma"] > 60:
        add("med", "Price is far above its 200-day average: chasing risk.")
    if m.get("pledge") is not None and m["pledge"] > 5:
        add("high", f"{m['pledge']:.0f}% of promoter shares are pledged.")
    if m.get("pledge_chg") is not None and m["pledge_chg"] > 4:
        add("high", f"Promoter pledge rose {m['pledge_chg']:.0f} pp over the past year.")
    if m.get("promoter_chg") is not None and m["promoter_chg"] < -1.5:
        add("high", f"Promoter holding fell {abs(m['promoter_chg']):.1f} pp over the past year.")
    if m.get("pit_net_cr") is not None and m["pit_net_cr"] < -3:
        add("med", f"Promoters/directors net sold about Rs {abs(m['pit_net_cr']):.0f} cr in 6 months.")
    if m.get("cfo_pat") is not None and m["cfo_pat"] < 0.4:
        add("high", f"Cash from ops is only {m['cfo_pat']:.0%} of reported profit — earnings quality risk.")
    if m.get("recv_days_chg_pct") is not None and m["recv_days_chg_pct"] > 30:
        add("med", f"Receivable days up {m['recv_days_chg_pct']:.0f}% — collections may be weakening.")
    if m.get("interest_coverage") is not None and m["interest_coverage"] < 2.5:
        add("high", f"Interest coverage only {m['interest_coverage']:.1f}x.")
    if m.get("acquisition") is True and (m.get("rev_cagr") or 0) > 25:
        add("med", "Recent goodwill jump: growth may be acquisition-led rather than organic.")
    return f


def classify(m: dict, flags: Optional[list] = None) -> dict[str, Any]:
    """
    Return outcome classification.

    Manual exceptions must stay watchlist until evidence resolves the gap;
    they cannot enter shortlist solely via override.
    """
    flags = flags or []
    G = GATES
    fail: list[str] = []
    unknown: list[str] = []
    watch: list[str] = []
    needs: list[str] = []

    sector = (m.get("fin_sector") or m.get("sector") or "").lower()
    if any(w in sector for w in ("bank", "finance", "insurance", "nbfc", "housing finance")):
        fail.append("financial sector excluded")

    sus = data_suspect(m)
    if sus:
        fail.append(sus)

    stale = stale_reason(m)
    if stale:
        unknown.append(stale)

    # Critical presence
    for k in CRITICAL_FIELDS:
        if m.get(k) is None:
            unknown.append(f"missing critical field: {k}")

    # Pledge: required for shortlist; if missing → watchlist (often NSE not yet fetched)
    if m.get("pledge") is None:
        watch.append("pledge not verified")
        needs.append("verified promoter pledge % from shareholding filing")

    # Size
    mc = m.get("mcap_cr")
    if mc is not None:
        if mc < G["min_mcap_cr"] or mc > G["max_mcap_cr"]:
            fail.append(f"mcap {mc:.0f} cr outside shortlist band ({G['min_mcap_cr']}-{G['max_mcap_cr']})")

    # Growth: multi-year AND recent sales; op-profit evidence required
    if m.get("rev_cagr") is not None and m["rev_cagr"] < G["min_sales_cagr"]:
        fail.append(f"sales CAGR {m['rev_cagr']:.0f}% below {G['min_sales_cagr']}%")

    if m.get("q_rev_yoy") is not None and m["q_rev_yoy"] < G["min_recent_sales"]:
        watch.append(f"recent sales growth {m['q_rev_yoy']:.0f}% weak vs {G['min_recent_sales']}% floor")
        needs.append("stronger same-quarter YoY revenue growth")

    # Profit evidence: q_profit_yoy required; margin alone cannot substitute
    if m.get("q_profit_yoy") is not None and m["q_profit_yoy"] < 0:
        watch.append("recent profit growth negative")
        needs.append("positive recent operating/profit growth")

    # Low-base / acquisition distortion
    if (
        m.get("profit_cagr") is not None
        and m.get("rev_cagr") is not None
        and m["profit_cagr"] > 80
        and m["rev_cagr"] < 10
    ):
        fail.append("profit CAGR extreme vs weak sales — possible low-base or one-off")

    # Quality
    if m.get("roce") is not None and m["roce"] < G["min_roce"]:
        fail.append(f"ROCE {m['roce']:.0f}% below {G['min_roce']}%")

    # Cash
    if m.get("cfo_pat") is not None:
        if m["cfo_pat"] < G["watch_cfo_pat"]:
            fail.append(f"CFO/PAT {m['cfo_pat']:.2f} too low")
        elif m["cfo_pat"] < G["min_cfo_pat"]:
            watch.append(f"CFO/PAT {m['cfo_pat']:.2f} below shortlist {G['min_cfo_pat']}")
            needs.append(f"CFO/PAT at least {G['min_cfo_pat']}")

    # Debt
    if m.get("de") is not None:
        if m["de"] > G["max_de_fail"]:
            fail.append(f"debt/equity {m['de']:.2f} above fail limit")
        elif m["de"] > G["max_de_shortlist"]:
            watch.append(f"debt/equity {m['de']:.2f} above shortlist {G['max_de_shortlist']}")
            needs.append(f"debt/equity ≤ {G['max_de_shortlist']}")

    # Ownership
    if m.get("pledge") is not None and m["pledge"] > G["max_pledge"]:
        fail.append(f"pledge {m['pledge']:.0f}% above {G['max_pledge']}%")

    if m.get("insider_pct") is not None:
        if m["insider_pct"] < G["min_promoter_fail"]:
            fail.append(f"promoter holding {m['insider_pct']:.0f}% too low")
        elif m["insider_pct"] < G["min_promoter"]:
            watch.append(f"promoter holding {m['insider_pct']:.0f}% below cohort preference {G['min_promoter']}%")
            needs.append(f"promoter holding ≥ {G['min_promoter']}% or documented exception remains watchlist")

    if m.get("dilution") is not None and m["dilution"] > G["max_dilution"]:
        fail.append(f"dilution {m['dilution']:.0f}% above {G['max_dilution']}%")

    # Valuation hypotheses
    pe, peg = m.get("pe"), m.get("peg")
    if pe is not None:
        pe_ok = pe <= G["max_pe"] or (peg is not None and peg <= G["max_peg"] and pe <= 40)
        if not pe_ok:
            fail.append(f"valuation not acceptable (PE {pe:.0f}, PEG {peg})")

    # Extreme but plausible working capital
    if m.get("recv_days_chg_pct") is not None and m["recv_days_chg_pct"] > G["max_recv_chg"]:
        fail.append(f"receivable days up {m['recv_days_chg_pct']:.0f}% — extreme deterioration")

    # Governance critical negatives from filings
    neg = m.get("neg_count")
    if neg is None:
        neg = m.get("neg_events") or 0
    if neg and neg > 0:
        fail.append("negative governance/regulatory filing")

    high = sum(1 for f in flags if f.get("sev") == "high")
    if high > CFG.get("max_high_flags", 1):
        fail.append(f"{high} high-severity red flags")

    # Manual override cannot create shortlist
    if m.get("manual_exception"):
        watch.append("manual exception — remains watchlist until evidence resolves gap")
        needs.append("documented evidence resolving the failed cohort preference")

    cov = evidence_coverage(m)

    if fail:
        outcome = "fail"
    elif unknown:
        outcome = "unknown"
    elif watch:
        outcome = "watchlist"
    else:
        outcome = "shortlist"

    return dict(
        outcome=outcome,
        fail=fail,
        unknown=unknown,
        watch=watch,
        needs=needs,  # what must change for watchlist → shortlist
        coverage=round(cov, 3),
        label={
            "fail": "Fail",
            "unknown": "Unknown",
            "watchlist": "Watchlist",
            "shortlist": "Research shortlist",
        }[outcome],
        disclaimer=(
            "Research shortlist is not a buy call, target price, or portfolio instruction. "
            "Thresholds are research-policy hypotheses until Phase 2 validation."
            if outcome == "shortlist"
            else None
        ),
    )


def eligible(m: dict, pil: dict, flags: list[dict]) -> tuple[bool, str]:
    """Backward-compatible wrapper: True only for research shortlist."""
    d = classify(m, flags)
    if d["outcome"] == "shortlist":
        return True, ""
    reasons = d["fail"] or d["unknown"] or d["watch"] or ["not shortlist"]
    return False, reasons[0]
