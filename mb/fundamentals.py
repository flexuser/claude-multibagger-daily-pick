"""Fundamental metrics from Yahoo Finance (free). Fail-soft field extraction."""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

import pandas as pd

from mb.config import THEMES, MOAT_WORDS
from mb.utils import num


def _row(df: Optional[pd.DataFrame], *labels: str) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    for lab in labels:
        if lab in df.index:
            s = df.loc[lab].dropna()
            if len(s):
                return s.sort_index(ascending=False)
    return None


def _cagr(s: Optional[pd.Series], years: int = 3) -> Optional[float]:
    if s is None or len(s) < 2:
        return None
    n = min(len(s) - 1, years)
    new, old = num(s.iloc[0]), num(s.iloc[n])
    if new is None or old is None or old <= 0 or new <= 0:
        return None
    return ((new / old) ** (1 / n) - 1) * 100


def _yoy(s: Optional[pd.Series]) -> Optional[float]:
    """YoY on quarterly series (index 0 vs index 4)."""
    if s is None or len(s) < 5:
        return None
    new, old = num(s.iloc[0]), num(s.iloc[4])
    if new is None or old is None or old <= 0:
        return None
    return (new / old - 1) * 100


def detect_themes(text: str) -> tuple[list[str], int]:
    t = " " + text.lower() + " "
    hits = [name for name, words in THEMES.items() if any(w in t for w in words)]
    moat = sum(1 for w in MOAT_WORDS if w in t)
    return hits, moat


def fetch_fundamentals(tk: str) -> dict[str, Any]:
    """
    Pull income / balance / cashflow + info from Yahoo.
    Returns a flat metric dict ready for scoring.
    """
    import yfinance as yf

    t = yf.Ticker(tk)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    def _safe_df(getter):
        try:
            df = getter()
            if df is None or (hasattr(df, "empty") and df.empty):
                return None
            return df
        except Exception:
            return None
    inc = _safe_df(lambda: t.financials)
    qinc = _safe_df(lambda: t.quarterly_financials)
    bs = _safe_df(lambda: t.balance_sheet)
    cf = _safe_df(lambda: t.cashflow)

    mcap = num(info.get("marketCap"))
    pe = num(info.get("trailingPE") or info.get("forwardPE"))
    peg = num(info.get("pegRatio"))
    de = num(info.get("debtToEquity"))
    insider = num(info.get("heldPercentInsiders"))
    inst = num(info.get("heldPercentInstitutions"))
    fcf = _row(cf, "Free Cash Flow")
    ebit = _row(inc, "EBIT", "Operating Income")
    ni = _row(inc, "Net Income", "Net Income Common Stockholders")
    rev = _row(inc, "Total Revenue", "Operating Revenue")
    qrev = _row(qinc, "Total Revenue", "Operating Revenue")
    qni = _row(qinc, "Net Income", "Net Income Common Stockholders")
    qebit = _row(qinc, "EBIT", "Operating Income")

    # Shares for dilution
    shares = _row(bs, "Ordinary Shares Number", "Share Issued")
    dilution = None
    if shares is not None and len(shares) >= 2:
        new_s, old_s = num(shares.iloc[0]), num(shares.iloc[min(len(shares) - 1, 3)])
        if new_s and old_s and old_s > 0:
            dilution = (new_s / old_s - 1) * 100

    # Operating margin & change
    op_margin = op_margin_chg = None
    if ebit is not None and rev is not None:
        jj = pd.concat([ebit, rev], axis=1, sort=True, keys=["e", "r"]).dropna()
        jj = jj[jj["r"] > 0].sort_index(ascending=False)
        if len(jj):
            mgn = jj["e"] / jj["r"] * 100
            op_margin = float(mgn.iloc[0])
            if len(mgn) >= 2:
                op_margin_chg = float(mgn.iloc[0] - mgn.iloc[min(len(mgn) - 1, 2)])

    q_opm_chg = None
    if qebit is not None and qrev is not None:
        jj = pd.concat([qebit, qrev], axis=1, sort=True, keys=["e", "r"]).dropna()
        jj = jj[jj["r"] > 0].sort_index(ascending=False)
        if len(jj) >= 5:
            mgn = jj["e"] / jj["r"] * 100
            q_opm_chg = float(mgn.iloc[0] - mgn.iloc[4])

    # ROCE approximation: EBIT / (total assets - current liabilities) or equity+debt
    roce = roce_chg = None
    equity = _row(bs, "Stockholders Equity", "Total Equity Gross Minority Interest")
    total_debt = _row(bs, "Total Debt", "Long Term Debt")
    if ebit is not None and equity is not None:
        capital = equity.copy()
        if total_debt is not None:
            capital = equity.add(total_debt.reindex(equity.index).fillna(0), fill_value=0)
        jj = pd.concat([ebit, capital], axis=1, sort=True, keys=["e", "c"]).dropna()
        jj = jj[jj["c"] > 0].sort_index(ascending=False)
        if len(jj):
            r = jj["e"] / jj["c"] * 100
            roce = float(r.iloc[0])
            if len(r) >= 2:
                roce_chg = float(r.iloc[0] - r.iloc[min(len(r) - 1, 2)])

    # Profit CAGR
    pcagr = _cagr(ni)

    # Capex intensity & CWIP growth
    capex = _row(cf, "Capital Expenditure")
    capex_rev_pct = None
    if capex is not None and rev is not None:
        jj = pd.concat([capex, rev], axis=1, sort=True, keys=["c", "r"]).dropna()
        jj = jj[jj["r"] > 0].sort_index(ascending=False)
        if len(jj):
            # Capex is usually negative in Yahoo CF
            capex_rev_pct = abs(float(jj["c"].iloc[0])) / float(jj["r"].iloc[0]) * 100

    def _g(s_: Optional[pd.Series]) -> Optional[float]:
        if s_ is None or len(s_) < 2:
            return None
        new, old = num(s_.iloc[0]), num(s_.iloc[1])
        if new is None or old is None or old <= 0:
            return None
        return (new / old - 1) * 100

    cwip = _row(bs, "Construction In Progress", "Work In Progress")
    gppe = _row(bs, "Gross PPE", "Net PPE", "Property Plant Equipment")

    # Acquisition signal from goodwill jump
    gw = _row(bs, "Goodwill")
    acq = None
    if gw is not None and len(gw) >= 2:
        g0, g1 = num(gw.iloc[0]), num(gw.iloc[1])
        if g0 is not None and g1 is not None and g1 > 0 and (g0 - g1) / g1 > 0.3:
            acq = True
        elif g0 is not None and g1 is not None:
            acq = False

    # Recent stock split
    split_recent = None
    try:
        sp = t.splits
        if sp is not None and len(sp):
            cutoff_ts = pd.Timestamp.now(tz=sp.index.tz) - pd.Timedelta(days=365)
            rec = sp[sp.index > cutoff_ts]
            if len(rec):
                split_recent = dict(date=str(rec.index[-1].date()), ratio=float(rec.iloc[-1]))
    except Exception:
        pass

    # Cash conversion: CFO / PAT over last ~3 years
    cfo = _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    cfo_pat = None
    if cfo is not None and ni is not None:
        jj = (
            pd.concat([cfo, ni], axis=1, sort=True, keys=["c", "n"])
            .dropna()
            .sort_index(ascending=False)
            .head(3)
        )
        if len(jj) >= 2 and jj["n"].sum() > 0:
            cfo_pat = float(jj["c"].sum() / jj["n"].sum())

    intexp = _row(inc, "Interest Expense", "Interest Expense Non Operating")
    icr = None
    if ebit is not None and intexp is not None and num(intexp.iloc[0]) and abs(float(intexp.iloc[0])) > 0:
        icr = float(ebit.iloc[0]) / abs(float(intexp.iloc[0]))

    recv = _row(bs, "Accounts Receivable", "Receivables", "Gross Accounts Receivable")
    recv_days = recv_days_chg_pct = None
    if recv is not None and rev is not None:
        jj = pd.concat([recv, rev], axis=1, sort=True, keys=["a", "r"]).dropna()
        jj = jj[jj["r"] > 0].sort_index(ascending=False)
        if len(jj):
            dd_ = (jj["a"] / jj["r"]) * 365
            recv_days = float(dd_.iloc[0])
            old_ = dd_.iloc[min(len(dd_) - 1, 3)]
            if len(dd_) >= 2 and old_ > 0:
                recv_days_chg_pct = float((dd_.iloc[0] / old_ - 1) * 100)

    def _latest(df_: Optional[pd.DataFrame]) -> Optional[str]:
        try:
            return str(max(df_.columns).date())
        except Exception:
            return None

    text = " ".join(str(info.get(k) or "") for k in ("longBusinessSummary", "industry", "sector"))
    themes, moat_kw = detect_themes(text)

    news = []
    try:
        for n in (t.news or [])[:6]:
            title = n.get("title") or (n.get("content") or {}).get("title")
            if title:
                news.append(title)
    except Exception:
        pass

    return dict(
        name=info.get("shortName") or info.get("longName") or tk,
        sector=info.get("industry") or info.get("sector") or "",
        blurb=(info.get("longBusinessSummary") or "")[:320],
        themes=themes,
        moat_kw=moat_kw,
        mcap_cr=(mcap / 1e7) if mcap else None,
        revenue_cr=(float(rev.iloc[0]) / 1e7) if rev is not None else None,
        pe=pe,
        peg=peg,
        rev_cagr=_cagr(rev),
        profit_cagr=pcagr,
        op_margin=op_margin,
        op_margin_chg=op_margin_chg,
        roce=roce,
        roce_chg=roce_chg,
        de=(de / 100) if de is not None else None,
        dilution=dilution,
        insider_pct=insider * 100 if insider is not None else None,
        inst_pct=inst * 100 if inst is not None else None,
        analysts=num(info.get("numberOfAnalystOpinions")),
        fcf_positive=(
            1 if (fcf is not None and num(fcf.iloc[0]) and num(fcf.iloc[0]) > 0) else 0
        )
        if fcf is not None
        else None,
        q_rev_yoy=_yoy(qrev),
        q_profit_yoy=_yoy(qni),
        q_opm_chg=q_opm_chg,
        cfo_pat=cfo_pat,
        interest_coverage=icr,
        recv_days=recv_days,
        recv_days_chg_pct=recv_days_chg_pct,
        fin_date=_latest(inc),
        q_date=_latest(qinc),
        fin_sector=info.get("sector"),
        capex_rev_pct=capex_rev_pct,
        cwip_growth=_g(cwip),
        gppe_growth=_g(gppe),
        acquisition=acq,
        split_recent=split_recent,
        news=news,
        fetched=dt.date.today().isoformat(),
    )
