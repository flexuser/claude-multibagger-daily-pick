"""
Pillar scoring, red flags, and hard eligibility gates tuned for
potential multi-year multibaggers in Indian small/mid caps.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from mb.config import CFG, WEIGHTS
from mb.utils import avg, ramp, ramp_inv


def trend_score(x: Optional[float]) -> Optional[float]:
    """Price vs 200-DMA: mild premium is good; extreme premium is chase risk."""
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
    if (m.get("rev_cagr") or 0) > 150 or (m.get("q_rev_yoy") or 0) > 300:
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


def score_pillars(m: dict) -> dict[str, Optional[float]]:
    rs = None
    if m.get("ret_6m") is not None and m.get("nifty_6m") is not None:
        rs = m["ret_6m"] - m["nifty_6m"]
    m["rs_6m"] = rs

    spread = None
    if m.get("profit_cagr") is not None and m.get("rev_cagr") is not None:
        spread = ramp(m["profit_cagr"] - m["rev_cagr"], -5, 15)

    accel = None
    if m.get("q_rev_yoy") is not None and m.get("rev_cagr") is not None:
        accel = m["q_rev_yoy"] - m["rev_cagr"]
    m["q_accel"] = accel

    theme_n = len(m.get("themes") or [])

    deliv = m.get("delivery_pct")
    deliv_score = ramp(deliv, 30, 60) if deliv is not None else None

    # RSI: prefer not extreme overbought for entry quality
    rsi = m.get("rsi_14")
    rsi_score = None
    if rsi is not None:
        if 40 <= rsi <= 65:
            rsi_score = 90.0
        elif 30 <= rsi < 40 or 65 < rsi <= 75:
            rsi_score = 60.0
        elif rsi < 30:
            rsi_score = 45.0  # oversold — possible value, not momentum confirm
        else:
            rsi_score = 25.0  # extended

    # Trend structure (higher highs/lows)
    struct = m.get("trend_structure")
    struct_score = 80.0 if struct == 1 else (35.0 if struct == 0 else None)

    # Golden cross proxy
    ma_x = m.get("ma50_vs_200")
    ma_score = ramp(ma_x, -5, 8) if ma_x is not None else None

    # Policy keyword hits in blurb/news/filings (soft)
    pol = m.get("policy_hits")
    pol_score = ramp(pol, 0, 3) if pol is not None else None

    # Theme peer relative strength (sector sentiment proxy)
    theme_rs = m.get("theme_rs_6m")
    theme_rs_score = ramp(theme_rs, -15, 20) if theme_rs is not None else None

    # News headline sentiment
    ns = m.get("news_sentiment")
    ns_score = ramp(ns, 30, 75) if ns is not None else None

    # Market regime: mild penalty in risk_off (not a hard reject)
    regime = m.get("market_regime")
    regime_score = {"risk_on": 75.0, "neutral": 55.0, "risk_off": 30.0}.get(regime)

    return dict(
        runway=avg([
            min(theme_n, 2) / 2 * 100,
            ramp_inv(m.get("revenue_cr"), 300, 4000),
            ramp(m.get("rev_cagr"), 12, 40),
            pol_score,
        ]),
        moat=avg([
            ramp(m.get("roce"), 12, 30),
            ramp(m.get("op_margin"), 10, 25),
            min(m.get("moat_kw") or 0, 3) / 3 * 100,
            None if m.get("roce_chg") is None else (100 if m["roce_chg"] >= -2 else 30),
        ]),
        proof=avg([
            ramp(m.get("rev_cagr"), 12, 40),
            ramp(m.get("q_rev_yoy"), 8, 45),
            ramp(accel, -5, 18),
            ramp(m.get("q_opm_chg"), -1, 4),
            ramp(m.get("profit_cagr"), 12, 40),
        ]),
        leverage=avg([
            ramp(m.get("op_margin_chg"), -2, 6),
            spread,
            ramp(m.get("roce_chg"), -2, 8),
            ramp(m.get("q_profit_yoy"), 0, 50),
        ]),
        quality=avg([
            ramp(m.get("roce"), 12, 28),
            ramp_inv(m.get("de"), 0, 1.2),
            ramp_inv(m.get("dilution"), 0, 12),
            ramp(m.get("insider_pct"), 30, 65),
            None if m.get("fcf_positive") is None else (100 if m["fcf_positive"] else 25),
            ramp(m.get("cfo_pat"), 0.5, 1.1),
            icr_score(m),
            ramp_inv(m.get("recv_days_chg_pct"), 0, 35),
        ]),
        discovery=avg([
            ramp_inv(m.get("mcap_cr"), 1200, 22000),
            ramp_inv(m.get("inst_pct"), 5, 35),
            ramp_inv(m.get("analysts"), 1, 12),
        ]),
        valuation=avg([
            ramp_inv(m.get("peg"), 0.8, 2.5),
            ramp_inv(m.get("pe"), 20, 80),
        ]),
        confirm=avg([
            trend_score(m.get("above_200dma")),
            ramp(m.get("from_52w_high"), -35, -5),
            ramp(rs, -8, 35),
            ramp(m.get("vol_ratio"), 0.85, 1.5),
            deliv_score,
            rsi_score,
            struct_score,
            ma_score,
        ]),
        ownership=avg([
            ramp(m.get("promoter_chg"), -1.5, 3),
            ramp_inv(m.get("pledge"), 0, 18),
            ramp_inv(m.get("pledge_chg"), -2, 2),
            ramp(m.get("fii_chg"), -1, 3),
            ramp(m.get("dii_chg"), -1, 3),
            ramp(m.get("pit_net_cr"), -1, 4),
        ]),
        catalyst=avg([
            m.get("event_score"),
            ramp(m.get("capex_rev_pct"), 4, 18),
            ramp(m.get("cwip_growth"), 15, 100),
            ramp(m.get("gppe_growth"), 5, 40),
            None if m.get("acquisition") is None else (75 if m["acquisition"] else 25),
        ]),
        context=avg([
            theme_rs_score,
            ns_score,
            regime_score,
            pol_score,
            ramp(m.get("ret_1m"), -10, 15),
        ]),
    )


def composite(p: dict) -> Optional[float]:
    num_, den = 0.0, 0.0
    for k, w in WEIGHTS.items():
        v = p.get(k)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv != fv:  # NaN
            continue
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
    if m.get("pledge") is not None and m["pledge"] > 15:
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


def eligible(m: dict, pil: dict, flags: list[dict]) -> tuple[bool, str]:
    """
    Hard gates for a credible multibagger candidate.
    Returns (ok, reason_if_rejected).
    """
    # Sector
    sector = (m.get("fin_sector") or m.get("sector") or "").lower()
    if any(w in sector for w in ("bank", "finance", "insurance", "nbfc", "housing finance")):
        return False, "financial sector"

    # Data quality
    sus = data_suspect(m)
    if sus:
        return False, sus
    stale = stale_reason(m)
    if stale:
        return False, stale

    # Size & liquidity already applied upstream; re-check mcap
    mc = m.get("mcap_cr")
    if mc is not None and (mc < CFG["min_mcap_cr"] or mc > CFG["max_mcap_cr"]):
        return False, f"mcap {mc:.0f} cr outside band"

    # Growth floor — require either solid CAGR or strong recent quarter
    growth_ok = (
        (m.get("rev_cagr") is not None and m["rev_cagr"] >= CFG["min_growth"])
        or (m.get("q_rev_yoy") is not None and m["q_rev_yoy"] >= CFG["min_growth"])
        or (m.get("profit_cagr") is not None and m["profit_cagr"] >= CFG["min_growth"])
    )
    if not growth_ok:
        return False, "insufficient growth"

    # Profitability
    if m.get("op_margin") is not None and m["op_margin"] < 5:
        return False, "operating margin too low"
    if m.get("roce") is not None and m["roce"] < CFG["min_roce"]:
        return False, f"ROCE below {CFG['min_roce']}%"

    # Balance sheet quality
    if m.get("de") is not None and m["de"] > CFG["max_de"]:
        return False, "debt too high"
    if m.get("dilution") is not None and m["dilution"] > CFG["max_dilution"]:
        return False, "excessive dilution"
    if m.get("pledge") is not None and m["pledge"] > CFG["max_pledge"]:
        return False, f"pledge {m['pledge']:.0f}% above limit"

    # Negative filings from NSE signals
    neg = m.get("neg_count")
    if neg is None:
        neg = m.get("neg_events") or 0
    if neg and neg > 0:
        return False, "negative filing"

    # Red-flag budget
    high = sum(1 for f in flags if f.get("sev") == "high")
    if high > CFG["max_high_flags"]:
        return False, f"{high} high red flags"

    # Pillar coverage
    present = sum(1 for v in pil.values() if v is not None)
    if present < CFG["min_pillars"]:
        return False, f"only {present} pillars populated"

    # Prefer still-undiscovered names (soft — only reject extreme cases)
    if m.get("inst_pct") is not None and m["inst_pct"] > 55:
        return False, "already heavily institutional"
    if m.get("analysts") is not None and m["analysts"] > 20:
        return False, "already heavily covered"

    return True, ""
