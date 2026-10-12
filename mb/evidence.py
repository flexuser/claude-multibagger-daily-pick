"""Human-readable evidence rows, thesis, and exit triggers for the pick page."""
from __future__ import annotations

from mb.utils import fmt


def build_evidence(m: dict) -> list[dict]:
    E: list[dict] = []

    def add(group, label, value, ok, why):
        E.append(dict(group=group, label=label, value=value, ok=ok, why=why))

    th = m.get("themes") or []
    add(
        "Runway", "Structural theme",
        ", ".join(th) if th else "none detected", bool(th),
        "Business description matches a long-cycle growth theme (keyword match — confirm by reading it).",
    )
    add(
        "Runway", "Revenue base",
        f"Rs {fmt(m.get('revenue_cr'))} cr",
        None if m.get("revenue_cr") is None else m["revenue_cr"] < 2500,
        "Small base means a real opportunity can still move the numbers materially.",
    )
    add(
        "Runway", "Revenue CAGR, 3 years",
        fmt(m.get("rev_cagr"), 1, "%"),
        None if m.get("rev_cagr") is None else m["rev_cagr"] >= 18,
        "Sustained growth of ~20%+ compounds into multi-bagger territory over a cycle.",
    )
    add(
        "Proof", "Latest quarter revenue, YoY",
        fmt(m.get("q_rev_yoy"), 1, "%"),
        None if m.get("q_rev_yoy") is None else m["q_rev_yoy"] >= 18,
        "Growth is continuing in the most recent results.",
    )
    add(
        "Proof", "Growth acceleration vs 3y trend",
        fmt(m.get("q_accel"), 1, " pp"),
        None if m.get("q_accel") is None else m["q_accel"] > 0,
        "Latest quarter growing faster than the 3-year pace — closest free proxy for a rising order book.",
    )
    add(
        "Proof", "Latest quarter margin vs year ago",
        fmt(m.get("q_opm_chg"), 1, " pp"),
        None if m.get("q_opm_chg") is None else m["q_opm_chg"] > 0,
        "Margins expanding as volumes grow.",
    )
    add(
        "Leverage", "Operating margin",
        fmt(m.get("op_margin"), 1, "%"),
        None if m.get("op_margin") is None else m["op_margin"] >= 12,
        "Healthy margin leaves room to absorb cost shocks.",
    )
    add(
        "Leverage", "Margin change over ~3 years",
        fmt(m.get("op_margin_chg"), 1, " pp"),
        None if m.get("op_margin_chg") is None else m["op_margin_chg"] > 0,
        "Operating leverage: earnings growing faster than sales.",
    )
    add(
        "Leverage", "Profit CAGR vs revenue CAGR",
        f"{fmt(m.get('profit_cagr'), 1, '%')} vs {fmt(m.get('rev_cagr'), 1, '%')}",
        None if (m.get("profit_cagr") is None or m.get("rev_cagr") is None)
        else m["profit_cagr"] > m["rev_cagr"],
        "Profit outgrowing sales is a classic re-rating signature.",
    )
    roce_txt = fmt(m.get("roce"), 1, "%")
    if m.get("roce_chg") is not None:
        roce_txt += f" ({m['roce_chg']:+.1f} pp in ~3y)"
    add(
        "Quality", "ROCE",
        roce_txt,
        None if m.get("roce") is None else m["roce"] >= 15,
        "Returns on capital show whether growth creates shareholder value.",
    )
    add(
        "Quality", "Debt / equity",
        fmt(m.get("de"), 2),
        None if m.get("de") is None else m["de"] <= 0.7,
        "Low debt lets the company fund growth without dilutive equity or distress risk.",
    )
    add(
        "Quality", "Operating cash flow / profit, ~3y",
        fmt(m.get("cfo_pat"), 2, "x"),
        None if m.get("cfo_pat") is None else m["cfo_pat"] >= 0.7,
        "Earnings quality: are reported profits turning into cash?",
    )
    if m.get("interest_coverage") is not None:
        icr_txt = fmt(m.get("interest_coverage"), 1, "x")
        icr_ok = m["interest_coverage"] >= 5
    elif m.get("de") is not None and m["de"] < 0.05:
        icr_txt, icr_ok = "no interest burden", True
    else:
        icr_txt, icr_ok = "n/a", None
    add("Quality", "Interest coverage", icr_txt, icr_ok, "Can earnings comfortably service any debt?")
    add(
        "Quality", "Share dilution, ~3y",
        fmt(m.get("dilution"), 1, "%"),
        None if m.get("dilution") is None else m["dilution"] <= 5,
        "Heavy equity issuance steals upside from existing owners.",
    )
    add(
        "Discovery", "Market cap",
        f"Rs {fmt(m.get('mcap_cr'))} cr",
        None if m.get("mcap_cr") is None else m["mcap_cr"] < 8000,
        "Still small enough that a multi-year growth story can re-rate the stock.",
    )
    add(
        "Discovery", "Institutional holding",
        fmt(m.get("inst_pct"), 1, "%"),
        None if m.get("inst_pct") is None else m["inst_pct"] < 25,
        "Low institutional ownership leaves room for discovery.",
    )
    add(
        "Ownership", "Promoter holding",
        fmt(m.get("insider_pct"), 1, "%"),
        None if m.get("insider_pct") is None else m["insider_pct"] >= 40,
        "Skin in the game from the controlling shareholders.",
    )
    add(
        "Ownership", "Promoter pledge",
        fmt(m.get("pledge"), 1, "%"),
        None if m.get("pledge") is None else m["pledge"] <= 5,
        "Pledged shares can be force-sold in a market fall.",
    )
    if m.get("event_score") is not None:
        add(
            "Catalyst", "Event score (order wins, expansion, …)",
            fmt(m.get("event_score"), 0),
            m["event_score"] >= 20,
            "Recent exchange filings that point to capacity or demand expansion.",
        )
    if m.get("delivery_pct") is not None:
        add(
            "Confirm", "Avg delivery % (1M)",
            fmt(m.get("delivery_pct"), 1, "%"),
            m["delivery_pct"] >= 45,
            "High delivery suggests genuine investor interest, not just day-trading churn.",
        )
    if m.get("rsi_14") is not None:
        add(
            "Confirm", "RSI (14)",
            fmt(m.get("rsi_14"), 1),
            35 <= m["rsi_14"] <= 70,
            "Avoid chasing extreme overbought readings when possible.",
        )
    if m.get("theme_rs_6m") is not None:
        add(
            "Context", "6m return vs theme peers",
            fmt(m.get("theme_rs_6m"), 1, " pp"),
            m["theme_rs_6m"] > 0,
            "Positive means the stock is outperforming others in the same structural theme (sector sentiment proxy).",
        )
    if m.get("news_sentiment") is not None:
        add(
            "Context", "Headline sentiment (keyword)",
            fmt(m.get("news_sentiment"), 0),
            m["news_sentiment"] >= 50,
            "Crude keyword score on recent Yahoo headlines — not a full NLP model.",
        )
    if m.get("policy_hits"):
        add(
            "Context", "Policy / PLI keyword hits",
            str(int(m["policy_hits"])),
            m["policy_hits"] >= 1,
            "Mentions of PLI, Make in India, defence budget, etc. in blurb/news/filings — confirm real dependency.",
        )
    if m.get("market_regime"):
        add(
            "Context", "Nifty market regime",
            str(m["market_regime"]),
            m["market_regime"] != "risk_off",
            "Risk-off regimes make small-cap multi-bagger paths harder near-term.",
        )
    return E


def build_thesis(m: dict) -> str:
    parts = []
    th = m.get("themes") or []
    if th:
        parts.append(f"Plays the {' / '.join(th[:2])} theme")
    if m.get("rev_cagr") is not None:
        parts.append(f"with ~{m['rev_cagr']:.0f}% revenue CAGR")
    if m.get("q_accel") is not None and m["q_accel"] > 0:
        parts.append("and accelerating quarterly growth")
    if m.get("roce") is not None and m["roce"] >= 15:
        parts.append(f"on a {m['roce']:.0f}% ROCE base")
    if m.get("de") is not None and m["de"] < 0.5:
        parts.append("with a clean balance sheet")
    if not parts:
        return "Quantitative screen matched growth, quality and discovery filters."
    return " ".join(parts) + "."


def exit_triggers(m: dict) -> list[str]:
    triggers = [
        "Promoter pledge rises above 20% or promoter holding falls >3 pp in a year",
        "Two consecutive quarters of revenue decline or margin compression >200 bps",
        "Debt/equity crosses 1.5x without a clear, funded capacity plan",
        "Credible SEBI / governance / auditor red flag in exchange filings",
        "Thesis invalidated: structural theme demand collapses or customer concentration risk materialises",
    ]
    if m.get("acquisition"):
        triggers.insert(0, "Acquisition-led growth fails to convert into organic ROCE improvement")
    return triggers
