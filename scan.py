#!/usr/bin/env python3
"""
Daily multibagger scanner.

Pipeline
  1. Universe: NSE small / mid / micro cap constituents (downloaded, cached).
  2. Price stage: one bulk price download -> liquidity filter + technicals
     (trend, relative strength vs Nifty, volume accumulation).
  3. Fundamental stage: growth, margins, ROCE, dilution, cash flow, ownership,
     quarterly acceleration, themes, news. Cached in data/fundamentals.json and
     refreshed gradually (--max-fetch per run) so the whole universe rolls over
     in about a week without hammering Yahoo.
  4. Score every candidate on 8 pillars, apply hard filters, pick the top one.
  5. Write docs/index.html + docs/latest.json, and log the pick in
     data/picks.json so the page can show a live track record vs Nifty.

Run locally:   python scan.py --demo          (synthetic data, no network)
               python scan.py --max-fetch 50  (real data)
"""
import argparse
import datetime as dt
import io
import json
import math
import random
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from render import render_page
from signals import NSEClient, fetch_signals, LABELS, NEGATIVE
import diligence
import notify

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
UNIVERSE_CSV = DATA / "universe.csv"
CACHE_JSON = DATA / "fundamentals.json"
PICKS_JSON = DATA / "picks.json"
SIGNALS_JSON = DATA / "signals.json"
DD_JSON = DATA / "diligence.json"

CFG = dict(
    min_mcap_cr=300,          # skip nano caps (illiquid, easy to manipulate)
    max_mcap_cr=40000,        # a 10x from here needs a giant business
    min_turnover_cr=1.0,      # avg daily traded value, Rs crore, last 3 months
    min_price=15,
    ttl_days=7,               # refresh fundamentals older than this
    min_pillars=6,            # need data for at least this many of 8 pillars
    max_high_flags=1,         # more red flags than this = rejected
    min_growth=12,            # revenue CAGR % (or latest quarter YoY) required
    bench=4,                  # runner-ups shown
    signal_top_n=40,          # fetch NSE event/ownership signals for the top N by base score
    diligence_top_n=3,        # AI due diligence on up to this many finalists per day
    hysteresis=3.0,           # keep yesterday's pick unless beaten by this many points
    stale_annual_days=460,    # annual results older than this = stale, rejected
    max_pledge=25,            # % of promoter shares pledged: above this is rejected
)

WEIGHTS = dict(runway=12, moat=8, proof=16, leverage=14, quality=10,
               discovery=6, valuation=8, confirm=6, ownership=10, catalyst=10)

PILLAR_NAMES = dict(
    runway="Runway (theme + small base)", moat="Moat (proxy)",
    proof="Proof (growth acceleration)", leverage="Operating leverage",
    quality="Capital quality", discovery="Still undiscovered",
    valuation="Valuation vs growth", confirm="Market confirmation",
    ownership="Ownership and smart money", catalyst="Expansion and catalysts")

NSE_URLS = [  # (primary, fallback) per index list
    ("https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
     "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv"),
    ("https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
     "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv"),
    ("https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
     "https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv"),
]
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

THEMES = {
    "Defence and aerospace": ["defence", "defense", "aerospace", "radar", "missile", "military", "avionics", "naval", "unmanned", "drone"],
    "Electronics and semiconductors": ["electronic manufacturing", "ems ", "semiconductor", "printed circuit", "pcb", "electronic components", "display", "chip"],
    "Energy transition": ["solar", "renewable", "battery", "lithium", "electric vehicle", "wind", "green hydrogen", "energy storage", "transmission", "smart meter"],
    "Railways and infrastructure": ["railway", "metro", "wagon", "rolling stock", "infrastructure"],
    "Specialty chemicals and CDMO": ["specialty chemical", "agrochemical", "intermediate", "cdmo", "contract manufacturing", "fluorin"],
    "Digital and data centres": ["data centre", "data center", "cloud", "cyber", "artificial intelligence"],
    "Export manufacturing": ["precision component", "castings", "forgings", "export", "global customers"],
}
MOAT_WORDS = ["qualified", "certified", "approved", "licence", "license", "patent", "proprietary",
              "indigenous", "sole supplier", "mission-critical", "long-term contract", "in-house r&d",
              "design and development", "as9100", "nadcap", "regulated"]

VERIFY = [
    "Order book and its growth vs revenue (latest investor presentation or concall). Filing summaries are short; open the linked PDFs",
    "Export share and export margins (annual report segment note). Only export order announcements are detected, not margins",
    "Capex plan, how it is funded, and expected capacity timeline",
    "FII and DII trend from the latest shareholding pattern, if it shows n/a above",
    "Customer concentration and dependence on government orders",
    "Governance: auditor changes, related-party dealings, promoter track record",
    "Whether the growth is organic or came from a one-off order or acquisition",
]


# ----------------------------------------------------------------- helpers
def num(x):
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def clamp(x):
    return max(0.0, min(1.0, x))


def ramp(v, lo, hi):
    return None if v is None else clamp((v - lo) / (hi - lo)) * 100.0


def ramp_inv(v, lo, hi):
    r = ramp(v, lo, hi)
    return None if r is None else 100.0 - r


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def clean(o):
    """Make anything JSON-safe (numpy types, NaN -> None)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 4)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean(obj), indent=1))
    tmp.replace(path)  # atomic rename


# ---------------------------------------------------------------- universe
def load_universe():
    """NSE index constituents. Falls back to the last good download, then to
    universe_extra.txt (one Yahoo ticker per line, e.g. ASTRAMICRO.NS)."""
    tickers = []
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "text/csv,*/*", "Referer": "https://www.nseindia.com/"})
        s.get("https://www.nseindia.com", timeout=20)  # sets cookies NSE expects
        rows = []
        for urls in NSE_URLS:
            text = None
            for url in urls:
                try:
                    r = s.get(url, timeout=30)
                    r.raise_for_status()
                    text = r.text
                    break
                except Exception as e:
                    print(f"  {url.rsplit('/', 1)[-1]} failed from {url.split('/')[2]}: {str(e)[:60]}")
            if text is None:
                raise RuntimeError("both sources failed for one index list")
            df = pd.read_csv(io.StringIO(text))
            df.columns = [c.strip() for c in df.columns]
            for _, row in df.iterrows():
                rows.append({"ticker": str(row["Symbol"]).strip() + ".NS",
                             "name": str(row.get("Company Name", "")).strip()})
        udf = pd.DataFrame(rows).drop_duplicates("ticker")
        udf.to_csv(UNIVERSE_CSV, index=False)
        tickers = udf["ticker"].tolist()
        print(f"Universe: downloaded {len(tickers)} tickers from NSE")
    except Exception as e:
        print(f"NSE download failed ({e}); using cached universe")
        if UNIVERSE_CSV.exists():
            tickers = pd.read_csv(UNIVERSE_CSV)["ticker"].tolist()
    extra = ROOT / "universe_extra.txt"
    if extra.exists():
        tickers += [ln.strip() for ln in extra.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    tickers = list(dict.fromkeys(tickers))
    before = len(tickers)
    tickers = [t for t in tickers if "DUMMY" not in t.upper() and re.fullmatch(r"[A-Za-z0-9&\-]+\.(NS|BO)", t.strip())]
    if len(tickers) < before:
        print(f"Universe: dropped {before - len(tickers)} placeholder or invalid symbols (e.g. DUMMY... entries)")
    if not tickers:
        sys.exit("No universe available. Add tickers to universe_extra.txt (one per line, e.g. ASTRAMICRO.NS).")
    return tickers


# ------------------------------------------------------------- price stage
def tech_from_series(close, volume):
    close = close.dropna()
    if len(close) < 130:
        return None
    last = float(close.iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())
    vol = volume.reindex(close.index).fillna(0)
    v6 = float(vol.tail(126).mean()) or 1.0
    spark = close.tail(250).iloc[:: max(1, len(close.tail(250)) // 120)]
    return dict(
        price=round(last, 2),
        last_date=str(close.index[-1])[:10],
        ret_1y=round((last / float(close.iloc[0]) - 1) * 100, 1),
        ret_6m=round((last / float(close.iloc[-126]) - 1) * 100, 1),
        ret_3m=round((last / float(close.iloc[-63]) - 1) * 100, 1),
        above_200dma=round((last / ma200 - 1) * 100, 1),
        from_52w_high=round((last / float(close.max()) - 1) * 100, 1),
        vol_ratio=round(float(vol.tail(21).mean()) / v6, 2),
        turnover_cr=round(float((close * vol).tail(63).mean()) / 1e7, 2),
        spark=[round(float(x), 2) for x in spark.tolist()],
    )


def fetch_prices_real(tickers):
    import logging
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # we print our own summary below
    out = {}
    for i in range(0, len(tickers), 80):
        chunk = tickers[i:i + 80]
        try:
            df = yf.download(chunk, period="1y", interval="1d", group_by="ticker",
                             auto_adjust=True, threads=True, progress=False)
        except Exception as e:
            print(f"  price chunk failed: {e}")
            continue
        for tk in chunk:
            try:
                sub = df[tk] if isinstance(df.columns, pd.MultiIndex) else df
                t = tech_from_series(sub["Close"].squeeze(), sub["Volume"].squeeze())
                if t:
                    out[tk] = t
            except Exception:
                pass
        print(f"  prices {min(i + 80, len(tickers))}/{len(tickers)}")
        time.sleep(1)
    missing = [t for t in tickers if t not in out]
    if missing:
        print(f"  no usable price history for {len(missing)} of {len(tickers)} tickers "
              f"(delisted, renamed, newly listed or <130 days of data), e.g. {', '.join(missing[:8])}")
    nifty = None
    try:
        n = yf.download("^NSEI", period="1y", interval="1d", auto_adjust=True, progress=False)
        c = n["Close"].squeeze().dropna()
        nifty = dict(last=float(c.iloc[-1]), ret_6m=float((c.iloc[-1] / c.iloc[-126] - 1) * 100))
    except Exception as e:
        print(f"  Nifty fetch failed: {e}")
    return out, nifty


# ------------------------------------------------------- fundamental stage
def _row(df, *labels):
    if df is None or df.empty:
        return None
    for lab in labels:
        if lab in df.index:
            s = df.loc[lab].dropna()
            if len(s):
                return s.sort_index(ascending=False)
    return None


def _cagr(s, years=3):
    if s is None or len(s) < 2:
        return None
    n = min(len(s) - 1, years)
    new, old = num(s.iloc[0]), num(s.iloc[n])
    if new is None or old is None or old <= 0 or new <= 0:
        return None
    return ((new / old) ** (1 / n) - 1) * 100


def _yoy(s):
    if s is None or len(s) < 5:
        return None
    new, old = num(s.iloc[0]), num(s.iloc[4])
    if new is None or old is None or old <= 0:
        return None
    return (new / old - 1) * 100


def detect_themes(text):
    t = " " + text.lower() + " "
    hits = [name for name, words in THEMES.items() if any(w in t for w in words)]
    moat = sum(1 for w in MOAT_WORDS if w in t)
    return hits, moat


def fetch_fund_real(tk):
    import yfinance as yf
    t = yf.Ticker(tk)
    info = t.info or {}
    inc, bs, cf, qinc = t.financials, t.balance_sheet, t.cashflow, t.quarterly_financials

    rev = _row(inc, "Total Revenue", "Operating Revenue")
    opi = _row(inc, "Operating Income", "EBIT")
    ebit = _row(inc, "EBIT", "Operating Income")
    ni = _row(inc, "Net Income", "Net Income Common Stockholders")
    assets = _row(bs, "Total Assets")
    cl = _row(bs, "Current Liabilities", "Total Current Liabilities")
    shares = _row(bs, "Ordinary Shares Number", "Share Issued")
    fcf = _row(cf, "Free Cash Flow")

    op_margin = op_margin_chg = None
    if opi is not None and rev is not None:
        j = pd.concat([opi, rev], axis=1, sort=True, keys=["o", "r"]).dropna()
        j = j[j["r"] > 0]
        if len(j):
            m = ((j["o"] / j["r"]) * 100).sort_index(ascending=False)
            op_margin = float(m.iloc[0])
            if len(m) >= 2:
                op_margin_chg = float(m.iloc[0] - m.iloc[min(len(m) - 1, 3)])

    roce = roce_chg = None
    if ebit is not None and assets is not None and cl is not None:
        j = pd.concat([ebit, assets, cl], axis=1, sort=True, keys=["e", "a", "c"]).dropna()
        j["k"] = j["a"] - j["c"]
        j = j[j["k"] > 0]
        if len(j):
            r = ((j["e"] / j["k"]) * 100).sort_index(ascending=False)
            roce = float(r.iloc[0])
            if len(r) >= 2:
                roce_chg = float(r.iloc[0] - r.iloc[min(len(r) - 1, 3)])

    dilution = None
    if shares is not None and len(shares) >= 2:
        n = min(len(shares) - 1, 3)
        a, b = num(shares.iloc[0]), num(shares.iloc[n])
        if a and b and b > 0:
            dilution = (a / b - 1) * 100

    qrev = _row(qinc, "Total Revenue", "Operating Revenue")
    qop = _row(qinc, "Operating Income", "EBIT")
    qni = _row(qinc, "Net Income", "Net Income Common Stockholders")
    q_opm_chg = None
    if qrev is not None and qop is not None:
        j = pd.concat([qop, qrev], axis=1, sort=True, keys=["o", "r"]).dropna()
        j = j[j["r"] > 0].sort_index(ascending=False)
        if len(j) >= 5:
            q_opm_chg = float(j["o"].iloc[0] / j["r"].iloc[0] * 100 - j["o"].iloc[4] / j["r"].iloc[4] * 100)

    peg = num(info.get("trailingPegRatio")) or num(info.get("pegRatio"))
    pe = num(info.get("trailingPE"))
    pcagr = _cagr(ni)
    if peg is None and pe and pcagr and pcagr > 0:
        peg = pe / pcagr
    de = num(info.get("debtToEquity"))
    insider, inst, mcap = num(info.get("heldPercentInsiders")), num(info.get("heldPercentInstitutions")), num(info.get("marketCap"))

    capex = _row(cf, "Capital Expenditure")
    biz = _row(cf, "Purchase Of Business", "Net Business Purchase And Sale")
    cwip = _row(bs, "Construction In Progress")
    gppe = _row(bs, "Gross PPE")
    goodwill = _row(bs, "Goodwill")
    capex_rev_pct = None
    if capex is not None and rev is not None and num(capex.iloc[0]) is not None and num(rev.iloc[0]):
        capex_rev_pct = abs(float(capex.iloc[0])) / float(rev.iloc[0]) * 100

    def _g(s_):
        if s_ is None or len(s_) < 2 or not num(s_.iloc[1]) or float(s_.iloc[1]) <= 0 or num(s_.iloc[0]) is None:
            return None
        return (float(s_.iloc[0]) / float(s_.iloc[1]) - 1) * 100
    acq = False
    if biz is not None and any(num(x) and abs(num(x)) > 0 for x in biz.head(2)):
        acq = True
    gw = _g(goodwill)
    if gw is not None and gw > 20:
        acq = True
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

    cfo = _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    cfo_pat = None
    if cfo is not None and ni is not None:
        jj = pd.concat([cfo, ni], axis=1, sort=True, keys=["c", "n"]).dropna().sort_index(ascending=False).head(3)
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

    def _latest(df_):
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
        themes=themes, moat_kw=moat_kw,
        mcap_cr=(mcap / 1e7) if mcap else None,
        revenue_cr=(float(rev.iloc[0]) / 1e7) if rev is not None else None,
        pe=pe, peg=peg,
        rev_cagr=_cagr(rev), profit_cagr=pcagr,
        op_margin=op_margin, op_margin_chg=op_margin_chg,
        roce=roce, roce_chg=roce_chg,
        de=(de / 100) if de is not None else None, dilution=dilution,
        insider_pct=insider * 100 if insider is not None else None,
        inst_pct=inst * 100 if inst is not None else None,
        analysts=num(info.get("numberOfAnalystOpinions")),
        fcf_positive=(1 if (fcf is not None and num(fcf.iloc[0]) and num(fcf.iloc[0]) > 0) else 0) if fcf is not None else None,
        q_rev_yoy=_yoy(qrev), q_profit_yoy=_yoy(qni), q_opm_chg=q_opm_chg,
        cfo_pat=cfo_pat, interest_coverage=icr, recv_days=recv_days, recv_days_chg_pct=recv_days_chg_pct,
        fin_date=_latest(inc), q_date=_latest(qinc), fin_sector=info.get("sector"),
        capex_rev_pct=capex_rev_pct, cwip_growth=_g(cwip), gppe_growth=_g(gppe), acquisition=acq, split_recent=split_recent,
        news=news, fetched=dt.date.today().isoformat(),
    )


# ----------------------------------------------------------------- scoring
def trend_score(x):
    if x is None:
        return None
    if x < 0:
        return ramp(x, -30, 0) * 0.6
    if x <= 40:
        return 60 + x / 40 * 40
    return max(40, 100 - (x - 40) * 1.5)


def icr_score(m):
    # no interest expense and low debt = fully covered
    if m.get("interest_coverage") is None:
        return 100.0 if (m.get("de") is not None and m["de"] < 0.05) else None
    return ramp(m["interest_coverage"], 2, 10)


def data_suspect(m):
    if (m.get("rev_cagr") or 0) > 150 or (m.get("q_rev_yoy") or 0) > 300:
        return "revenue growth looks like a data error"
    if (m.get("op_margin") or 0) > 80 or (m.get("roce") or 0) > 150:
        return "margin or ROCE looks like a data error"
    return None


def stale_reason(m):
    d = m.get("fin_date")
    if d:
        try:
            if (dt.date.today() - dt.date.fromisoformat(d)).days > CFG["stale_annual_days"]:
                return f"latest annual results are dated {d}"
        except ValueError:
            pass
    return None


def score_pillars(m):
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
    return dict(
        runway=avg([min(theme_n, 2) / 2 * 100, ramp_inv(m.get("revenue_cr"), 300, 5000), ramp(m.get("rev_cagr"), 10, 35)]),
        moat=avg([ramp(m.get("roce"), 12, 30), ramp(m.get("op_margin"), 10, 25),
                  min(m.get("moat_kw") or 0, 3) / 3 * 100,
                  None if m.get("roce_chg") is None else (100 if m["roce_chg"] >= -2 else 30)]),
        proof=avg([ramp(m.get("rev_cagr"), 10, 35), ramp(m.get("q_rev_yoy"), 5, 40),
                   ramp(accel, -5, 15), ramp(m.get("q_opm_chg"), -1, 4)]),
        leverage=avg([ramp(m.get("op_margin_chg"), -2, 6), spread, ramp(m.get("roce_chg"), -2, 8),
                      ramp(m.get("q_profit_yoy"), 0, 50)]),
        quality=avg([ramp(m.get("roce"), 10, 25), ramp_inv(m.get("de"), 0, 1.5), ramp_inv(m.get("dilution"), 0, 15),
                     ramp(m.get("insider_pct"), 25, 60),
                     None if m.get("fcf_positive") is None else (100 if m["fcf_positive"] else 30),
                     ramp(m.get("cfo_pat"), 0.4, 1.0), icr_score(m), ramp_inv(m.get("recv_days_chg_pct"), 0, 40)]),
        discovery=avg([ramp_inv(m.get("mcap_cr"), 1500, 30000), ramp_inv(m.get("inst_pct"), 5, 40),
                       ramp_inv(m.get("analysts"), 2, 15)]),
        valuation=avg([ramp_inv(m.get("peg"), 1, 3), ramp_inv(m.get("pe"), 25, 100)]),
        confirm=avg([trend_score(m.get("above_200dma")), ramp(m.get("from_52w_high"), -40, -5),
                     ramp(rs, -10, 40), ramp(m.get("vol_ratio"), 0.8, 1.6)]),
        ownership=avg([ramp(m.get("promoter_chg"), -2, 3), ramp_inv(m.get("pledge"), 0, 25),
                       ramp_inv(m.get("pledge_chg"), -3, 3), ramp(m.get("fii_chg"), -1, 3),
                       ramp(m.get("dii_chg"), -1, 3), ramp(m.get("pit_net_cr"), -2, 5)]),
        catalyst=avg([m.get("event_score"), ramp(m.get("capex_rev_pct"), 3, 15), ramp(m.get("cwip_growth"), 10, 100),
                      ramp(m.get("gppe_growth"), 5, 40),
                      None if m.get("acquisition") is None else (80 if m["acquisition"] else 20)]),
    )


def composite(p):
    num_, den = 0.0, 0.0
    for k, w in WEIGHTS.items():
        if p.get(k) is not None:
            num_ += p[k] * w
            den += w
    return num_ / den if den else None


def red_flags(m):
    f = []

    def add(sev, t):
        f.append(dict(sev=sev, text=t))
    if m.get("dilution") is not None and m["dilution"] > 10:
        add("high", f"Share count up {m['dilution']:.0f}% in 3 years (dilution).")
    if m.get("de") is not None and m["de"] > 1.5:
        add("high", f"Debt/equity {m['de']:.1f}: a growth miss gets expensive.")
    if (m.get("peg") is not None and m["peg"] > 3) or (m.get("pe") and m["pe"] > 80 and (m.get("profit_cagr") or 0) < 25):
        add("high", "Valuation already prices in years of success.")
    if m.get("op_margin_chg") is not None and m["op_margin_chg"] < -1 and (m.get("rev_cagr") or 0) > 10:
        add("med", "Sales growing but margins shrinking.")
    if m.get("fcf_positive") == 0:
        add("med", "Free cash flow negative: growth may need outside funding.")
    if m.get("roce") is not None and m["roce"] < 8:
        add("med", f"ROCE only {m['roce']:.0f}%.")
    if m.get("inst_pct") is not None and m["inst_pct"] > 45:
        add("med", f"Institutions already hold {m['inst_pct']:.0f}%: less discovery upside.")
    if m.get("insider_pct") is not None and m["insider_pct"] < 25:
        add("med", f"Promoter holding only {m['insider_pct']:.0f}%.")
    if m.get("above_200dma") is not None and m["above_200dma"] > 70:
        add("med", "Price is far above its 200-day average: chasing risk.")
    if m.get("pledge") is not None and m["pledge"] > 20:
        add("high", f"{m['pledge']:.0f}% of promoter shares are pledged. Pledged shares can be force-sold in a fall.")
    if m.get("pledge_chg") is not None and m["pledge_chg"] > 5:
        add("high", f"Promoter pledge rose {m['pledge_chg']:.0f} pp over the past year.")
    if m.get("promoter_chg") is not None and m["promoter_chg"] < -2:
        add("high", f"Promoter holding fell {abs(m['promoter_chg']):.1f} pp over the past year.")
    if m.get("pit_net_cr") is not None and m["pit_net_cr"] < -5:
        add("med", f"Promoters/directors net sold about Rs {abs(m['pit_net_cr']):.0f} cr in 6 months.")
    if m.get("cfo_pat") is not None and m["cfo_pat"] < 0.3:
        add("high", f"Operating cash flow is only {m['cfo_pat']:.2f}x profit over 3 years. Profits are not turning into cash.")
    elif m.get("cfo_pat") is not None and m["cfo_pat"] < 0.7:
        add("med", f"Operating cash flow is {m['cfo_pat']:.2f}x profit over 3 years. Fast-growing firms often lag on working capital, but check receivables.")
    if m.get("interest_coverage") is not None and m["interest_coverage"] < 2:
        add("high", f"Interest coverage only {m['interest_coverage']:.1f}x.")
    elif m.get("interest_coverage") is not None and m["interest_coverage"] < 4:
        add("med", f"Interest coverage is thin at {m['interest_coverage']:.1f}x.")
    if m.get("recv_days_chg_pct") is not None and m["recv_days_chg_pct"] > 30:
        add("med", f"Receivable days up {m['recv_days_chg_pct']:.0f}% in 3 years: customers are paying slower.")
    if data_suspect(m):
        add("high", "Data check: " + data_suspect(m) + ".")
    if stale_reason(m):
        add("high", "Stale data: " + stale_reason(m) + ".")
    if (m.get("neg_events") or 0) > 0:
        add("high", "Recent filing flags a governance, distress, regulatory or pledge-invocation issue. Read it.")
    return f


def eligible(m, pil, flags):
    fin_text = f"{m.get('fin_sector') or ''} {m.get('sector') or ''}".lower()
    if any(w in fin_text for w in ("financial", "bank", "insurance", "credit services", "mortgage", "asset management")):
        return False, "financial company (ratios not comparable)"
    if data_suspect(m):
        return False, "suspect data"
    if stale_reason(m):
        return False, "stale financials"
    if m.get("mcap_cr") is None or not (CFG["min_mcap_cr"] <= m["mcap_cr"] <= CFG["max_mcap_cr"]):
        return False, "market cap outside range"
    if m.get("op_margin") is None or m["op_margin"] <= 0:
        return False, "not operationally profitable"
    g = max(m.get("rev_cagr") or -99, m.get("q_rev_yoy") or -99)
    if g < CFG["min_growth"]:
        return False, "growth below threshold"
    if m.get("pledge") is not None and m["pledge"] > CFG["max_pledge"]:
        return False, "promoter pledge too high"
    if (m.get("neg_events") or 0) > 0:
        return False, "negative filing (governance/distress/regulatory)"
    if sum(1 for v in pil.values() if v is not None) < CFG["min_pillars"]:
        return False, "not enough data"
    if sum(1 for x in flags if x["sev"] == "high") > CFG["max_high_flags"]:
        return False, "too many red flags"
    return True, ""


# ------------------------------------------------------ evidence + thesis
def _f(v, d=0, suffix=""):
    return "n/a" if v is None else f"{v:,.{d}f}{suffix}"


def build_evidence(m):
    E = []

    def add(group, label, value, ok, why):
        E.append(dict(group=group, label=label, value=value, ok=ok, why=why))
    th = m.get("themes") or []
    add("Runway", "Structural theme", ", ".join(th) if th else "none detected", bool(th),
        "Business description matches a long-cycle growth theme (keyword match, so confirm by reading it).")
    add("Runway", "Revenue base", f"Rs {_f(m.get('revenue_cr'))} cr", None if m.get("revenue_cr") is None else m["revenue_cr"] < 3000,
        "Small base means a big opportunity can move the numbers.")
    add("Runway", "Revenue CAGR, 3 years", _f(m.get("rev_cagr"), 1, "%"), None if m.get("rev_cagr") is None else m["rev_cagr"] >= 20, "Sustained growth of 20%+ compounds fast.")
    add("Proof", "Latest quarter revenue, YoY", _f(m.get("q_rev_yoy"), 1, "%"), None if m.get("q_rev_yoy") is None else m["q_rev_yoy"] >= 20, "Growth is continuing in the most recent results.")
    add("Proof", "Growth acceleration vs 3y trend", _f(m.get("q_accel"), 1, " pp"), None if m.get("q_accel") is None else m["q_accel"] > 0, "Latest quarter growing faster than the 3-year pace. Closest free proxy for a rising order book.")
    add("Proof", "Latest quarter margin vs year ago", _f(m.get("q_opm_chg"), 1, " pp"), None if m.get("q_opm_chg") is None else m["q_opm_chg"] > 0, "Margins expanding as volumes grow.")
    add("Leverage", "Operating margin", _f(m.get("op_margin"), 1, "%"), None if m.get("op_margin") is None else m["op_margin"] >= 15, "Healthy margin leaves room to absorb costs.")
    add("Leverage", "Margin change over 3 years", _f(m.get("op_margin_chg"), 1, " pp"), None if m.get("op_margin_chg") is None else m["op_margin_chg"] > 0, "Operating leverage: earnings growing faster than sales.")
    add("Leverage", "Profit CAGR vs revenue CAGR", f"{_f(m.get('profit_cagr'), 1, '%')} vs {_f(m.get('rev_cagr'), 1, '%')}", None if (m.get("profit_cagr") is None or m.get("rev_cagr") is None) else m["profit_cagr"] > m["rev_cagr"], "Profit outgrowing sales is the signature of a re-rating.")
    add("Quality", "ROCE", _f(m.get("roce"), 1, "%") + (f" ({m['roce_chg']:+.1f} pp in 3y)" if m.get("roce_chg") is not None else ""), None if m.get("roce") is None else m["roce"] >= 15, "Returns on capital show if growth creates value.")
    add("Quality", "Debt / equity", _f(m.get("de"), 2), None if m.get("de") is None else m["de"] <= 0.8, "Low debt lets the company fund growth safely.")
    add("Quality", "Operating cash flow / profit, 3 years", _f(m.get("cfo_pat"), 2, "x"), None if m.get("cfo_pat") is None else m["cfo_pat"] >= 0.7, "Earnings quality: are profits turning into cash?")
    add("Quality", "Interest coverage", _f(m.get("interest_coverage"), 1, "x") if m.get("interest_coverage") is not None else ("no interest burden" if (m.get("de") is not None and m["de"] < 0.05) else "n/a"), None if (m.get("interest_coverage") is None and not (m.get("de") is not None and m["de"] < 0.05)) else (m.get("interest_coverage") is None or m["interest_coverage"] >= 5), "Can earnings comfortably service the debt?")
    add("Quality", "Receivable days change, 3 years", _f(m.get("recv_days_chg_pct"), 0, "%"), None if m.get("recv_days_chg_pct") is None else m["recv_days_chg_pct"] <= 20, "Rising receivable days can mean aggressive sales booking or weak customers.")
    add("Quality", "Share count change, 3 years", _f(m.get("dilution"), 1, "%"), None if m.get("dilution") is None else m["dilution"] <= 3, "Little dilution means holders keep their share of the upside.")
    add("Quality", "Free cash flow", "positive" if m.get("fcf_positive") == 1 else ("negative" if m.get("fcf_positive") == 0 else "n/a"), None if m.get("fcf_positive") is None else m["fcf_positive"] == 1, "Growth that funds itself.")
    add("Quality", "Promoter / insider holding", _f(m.get("insider_pct"), 1, "%"), None if m.get("insider_pct") is None else m["insider_pct"] >= 40, "Owners with skin in the game.")
    add("Undiscovered", "Market cap", f"Rs {_f(m.get('mcap_cr'))} cr", None if m.get("mcap_cr") is None else m["mcap_cr"] <= 10000, "Smaller companies have more room to multiply.")
    add("Undiscovered", "Institutional holding", _f(m.get("inst_pct"), 1, "%"), None if m.get("inst_pct") is None else m["inst_pct"] <= 25, "Low institutional ownership leaves room for new buyers.")
    add("Undiscovered", "Analysts covering", _f(m.get("analysts")), None if m.get("analysts") is None else m["analysts"] <= 6, "Few analysts, less crowded.")
    ev_c = m.get("event_counts")
    add("Ownership", "Promoter holding change, ~1 year", _f(m.get("promoter_chg"), 1, " pp"), None if m.get("promoter_chg") is None else m["promoter_chg"] > 0, "Promoters adding to their stake is a strong vote of confidence.")
    add("Ownership", "Promoter shares pledged", _f(m.get("pledge"), 1, "%") + (f" ({m['pledge_chg']:+.1f} pp in a year)" if m.get("pledge_chg") is not None else ""), None if m.get("pledge") is None else m["pledge"] <= 5, "Low pledge means no forced-selling risk.")
    add("Ownership", "Promoter/director open-market buying, 6 months", ("n/a" if m.get("pit_net_cr") is None else f"Rs {m['pit_net_cr']:+.1f} cr ({m.get('pit_buys', 0)} buys, {m.get('pit_sells', 0)} sells)"), None if m.get("pit_net_cr") is None else m["pit_net_cr"] > 0, "Insiders buying with their own money, from SEBI insider-trading disclosures.")
    add("Ownership", "FII holding change, ~1 year", _f(m.get("fii_chg"), 1, " pp"), None if m.get("fii_chg") is None else m["fii_chg"] > 0, "Foreign funds building a position.")
    add("Ownership", "DII holding change, ~1 year", _f(m.get("dii_chg"), 1, " pp"), None if m.get("dii_chg") is None else m["dii_chg"] > 0, "Domestic funds building a position.")
    add("Catalysts", "Capex as % of revenue", _f(m.get("capex_rev_pct"), 1, "%"), None if m.get("capex_rev_pct") is None else m["capex_rev_pct"] >= 6, "Heavy reinvestment signals an expansion phase.")
    add("Catalysts", "Capital work in progress growth", _f(m.get("cwip_growth"), 0, "%"), None if m.get("cwip_growth") is None else m["cwip_growth"] > 20, "Plants under construction today become capacity tomorrow.")
    add("Catalysts", "Gross fixed assets growth", _f(m.get("gppe_growth"), 0, "%"), None if m.get("gppe_growth") is None else m["gppe_growth"] >= 15, "Capacity actually added.")
    add("Catalysts", "Acquisition in last 2 years", "yes" if m.get("acquisition") else ("no" if m.get("acquisition") is not None else "n/a"), None if m.get("acquisition") is None else bool(m["acquisition"]), "From cash-flow business purchases or a goodwill jump. Check whether it is value-adding.")
    if ev_c is not None:
        add("Catalysts", "Order wins, last 120 days", str(ev_c.get("order_win", 0)), ev_c.get("order_win", 0) > 0, "Counted from exchange filings.")
        add("Catalysts", "Expansion / capacity filings", str(ev_c.get("expansion", 0) + ev_c.get("capacity_double", 0)), (ev_c.get("expansion", 0) + ev_c.get("capacity_double", 0)) > 0, "Announced plants, capacity additions or doubling.")
        add("Catalysts", "Export-related filings", str(ev_c.get("export", 0)), ev_c.get("export", 0) > 0, "Export orders or overseas customers. Export margins are not available.")
    sr = m.get("split_recent")
    add("Catalysts", "Bonus or split in last year", (f"{sr['ratio']:.0f}-for-1 on {sr['date']}" if sr else "none"), None, "Improves liquidity and signals management confidence, but creates no value by itself. Worth only a few points in the score.")
    add("Valuation", "PE / PEG", f"{_f(m.get('pe'), 1)} / {_f(m.get('peg'), 2)}", None if m.get("peg") is None else m["peg"] <= 2, "Is the price reasonable for the growth?")
    add("Market", "Price vs 200-day average", _f(m.get("above_200dma"), 1, "%"), None if m.get("above_200dma") is None else 0 <= m["above_200dma"] <= 60, "Uptrend, but not stretched.")
    add("Market", "6-month return vs Nifty", _f(m.get("rs_6m"), 1, " pp"), None if m.get("rs_6m") is None else m["rs_6m"] > 0, "Market is already starting to notice.")
    add("Market", "Volume, last month vs 6-month avg", _f(m.get("vol_ratio"), 2, "x"), None if m.get("vol_ratio") is None else m["vol_ratio"] >= 1.1, "Rising volume hints at accumulation.")
    return E


def build_thesis(m):
    parts = []
    th = m.get("themes") or []
    if th:
        parts.append(f"Operates in {th[0].lower()}" + (f" and {th[1].lower()}" if len(th) > 1 else "") + ".")
    if m.get("revenue_cr") is not None and m.get("rev_cagr") is not None:
        parts.append(f"Revenue of Rs {m['revenue_cr']:,.0f} cr has compounded at {m['rev_cagr']:.0f}% a year over three years.")
    if m.get("q_rev_yoy") is not None:
        parts.append(f"The latest quarter grew {m['q_rev_yoy']:.0f}% year on year.")
    if m.get("op_margin_chg") is not None and m.get("roce") is not None:
        parts.append(f"Operating margin moved {m['op_margin_chg']:+.1f} pp while ROCE sits at {m['roce']:.0f}%.")
    if m.get("analysts") is not None and m.get("inst_pct") is not None:
        parts.append(f"Only {m['analysts']:.0f} analysts cover it and institutions hold {m['inst_pct']:.0f}%, so it may not be widely discovered.")
    return " ".join(parts)


def exit_triggers(m):
    t = []
    if m.get("q_rev_yoy") is not None:
        t.append(f"Quarterly revenue growth falls below {max(10, m['q_rev_yoy'] * 0.5):.0f}% year on year (now {m['q_rev_yoy']:.0f}%).")
    if m.get("op_margin") is not None:
        t.append(f"Operating margin drops below {max(5, m['op_margin'] - 4):.0f}% (now {m['op_margin']:.0f}%).")
    if m.get("roce") is not None:
        t.append(f"ROCE falls below {max(10, m['roce'] * 0.7):.0f}% (now {m['roce']:.0f}%).")
    t.append("Promoter pledge appears or rises above 10%, or promoter holding falls more than 2 pp.")
    t.append("Operating cash flow stays below half of profit for two years running.")
    if m.get("above_200dma") is not None:
        t.append("Weekly close below the 200-day average on rising volume.")
    t.append("Order book or order inflow stops growing faster than revenue at the next concall.")
    return t


def dd_context(s_):
    m = s_["m"]

    def g(k, d=1, suf=""):
        v = m.get(k)
        return "n/a" if v is None else f"{v:.{d}f}{suf}"
    facts = (f"Revenue CAGR 3y {g('rev_cagr', 0, '%')}, latest quarter revenue YoY {g('q_rev_yoy', 0, '%')}, "
             f"operating margin {g('op_margin', 1, '%')} (change {g('op_margin_chg', 1, ' pp')} over 3y), ROCE {g('roce', 0, '%')}, "
             f"debt/equity {g('de', 2)}, cash flow/profit {g('cfo_pat', 2, 'x')}, PE {g('pe', 0)}, "
             f"promoter holding {g('insider_pct', 0, '%')}, institutional {g('inst_pct', 0, '%')}, pledge {g('pledge', 0, '%')}")
    return dict(ticker=s_["ticker"], name=m.get("name"), sector=m.get("sector"), mcap_cr=None if m.get("mcap_cr") is None else round(m["mcap_cr"]),
                facts=facts, flags="\n".join("- " + f["text"] for f in s_["flags"]),
                events="\n".join(f"- {e['date']}: {e['text'][:140]}" for e in (m.get("events") or [])[:6]))


def track_episodes(picks, prices, nifty):
    """Group consecutive identical picks into one episode so repeats aren't double counted."""
    eps = []
    for p in picks:
        if eps and eps[-1]["ticker"] == p["ticker"]:
            eps[-1]["last"] = p["date"]
            eps[-1]["days"] += 1
        else:
            eps.append(dict(ticker=p["ticker"], name=p["name"], start=p["date"], last=p["date"], days=1,
                            price=p["price"], nifty0=p.get("nifty"), score=p["score"]))
    out = []
    for e in eps:
        now = prices.get(e["ticker"], {}).get("price")
        ret = (now / e["price"] - 1) * 100 if (now and e["price"]) else None
        nr = (nifty["last"] / e["nifty0"] - 1) * 100 if (nifty and e.get("nifty0")) else None
        out.append(dict(start=e["start"], last=e["last"], days=e["days"], ticker=e["ticker"], name=e["name"],
                        price=e["price"], score=e["score"], ret=ret, nifty_ret=nr, active=(e is eps[-1])))
    done = [x for x in out if x["ret"] is not None and x["nifty_ret"] is not None]
    summary = dict(episodes=len(out), measured=len(done),
                   beat=sum(1 for x in done if x["ret"] > x["nifty_ret"]),
                   avg_excess=(sum(x["ret"] - x["nifty_ret"] for x in done) / len(done)) if done else None)
    return out[::-1][:40], summary


# ------------------------------------------------------------------- demo
def demo_data():
    rnd = random.Random(7)
    prices, funds = {}, {}
    themes = list(THEMES)
    for i in range(1, 61):
        tk = f"DEMO{i:02d}.NS"
        n = 260
        drift = rnd.uniform(-0.0003, 0.0018)
        c = 100 * np.exp(np.cumsum(np.random.default_rng(i).normal(drift, 0.02, n)))
        idx = pd.date_range(end=dt.date.today(), periods=n, freq="D")
        close = pd.Series(c, index=idx)
        vol = pd.Series(np.random.default_rng(i + 99).integers(2e5, 2e6, n) * (1 + 0.4 * (i % 3 == 0) * np.linspace(0, 1, n)), index=idx)
        t = tech_from_series(close, vol)
        t["turnover_cr"] = round(rnd.uniform(1.5, 30), 2)
        prices[tk] = t
        good = i % 7 == 0
        th = [themes[i % len(themes)]] if (good or i % 3 == 0) else []
        funds[tk] = dict(
            name=f"Demo Company {i:02d}", sector="Synthetic", blurb="Synthetic company for previewing the page.",
            themes=th, moat_kw=rnd.randint(0, 3),
            mcap_cr=rnd.uniform(500, 35000) if not good else rnd.uniform(900, 4000),
            revenue_cr=rnd.uniform(200, 4000) if not good else rnd.uniform(300, 1200),
            pe=rnd.uniform(15, 90), peg=rnd.uniform(0.7, 4) if not good else rnd.uniform(0.8, 1.8),
            rev_cagr=rnd.uniform(5, 30) if not good else rnd.uniform(28, 45),
            profit_cagr=rnd.uniform(0, 30) if not good else rnd.uniform(35, 60),
            op_margin=rnd.uniform(5, 22) if not good else rnd.uniform(18, 26),
            op_margin_chg=rnd.uniform(-3, 3) if not good else rnd.uniform(3, 7),
            roce=rnd.uniform(6, 20) if not good else rnd.uniform(20, 32), roce_chg=rnd.uniform(-3, 4) if not good else rnd.uniform(3, 8),
            de=rnd.uniform(0, 2) if not good else rnd.uniform(0, 0.3), dilution=rnd.uniform(0, 14) if not good else rnd.uniform(0, 2),
            insider_pct=rnd.uniform(20, 70), inst_pct=rnd.uniform(3, 50) if not good else rnd.uniform(3, 15),
            analysts=rnd.randint(1, 20) if not good else rnd.randint(1, 5), fcf_positive=rnd.choice([0, 1]) if not good else 1,
            q_rev_yoy=rnd.uniform(0, 35) if not good else rnd.uniform(35, 60), q_profit_yoy=rnd.uniform(-10, 40) if not good else rnd.uniform(40, 90),
            q_opm_chg=rnd.uniform(-2, 3) if not good else rnd.uniform(2, 5),
            cfo_pat=rnd.uniform(0.2, 1.3) if not good else rnd.uniform(0.8, 1.2), interest_coverage=rnd.uniform(1, 15) if not good else rnd.uniform(8, 30),
            recv_days_chg_pct=rnd.uniform(-10, 50) if not good else rnd.uniform(-10, 15), fin_sector="Industrials",
            fin_date=dt.date.today().isoformat(), q_date=dt.date.today().isoformat(),
            capex_rev_pct=rnd.uniform(1, 12) if not good else rnd.uniform(8, 18), cwip_growth=rnd.uniform(-20, 60) if not good else rnd.uniform(40, 120),
            gppe_growth=rnd.uniform(0, 25) if not good else rnd.uniform(20, 45), acquisition=bool(good and i % 14 == 0), split_recent=None,
            news=["Synthetic headline for preview only"], fetched=dt.date.today().isoformat())
    return prices, funds, dict(last=22000.0, ret_6m=6.0)


def demo_signals(tk):
    rnd = random.Random(tk)
    good = int(tk[4:6]) % 7 == 0
    cats = [["order_win"], ["expansion"], ["export", "order_win"]] if good else ([["approval"]] if rnd.random() < 0.5 else [])
    labels = {"order_win": "Order win", "expansion": "Expansion", "export": "Export", "approval": "Approval"}
    texts = {"order_win": "Synthetic order announcement for preview", "expansion": "Synthetic capacity expansion announcement for preview",
             "export": "Synthetic export order for preview", "approval": "Synthetic approval for preview"}
    events = [dict(date=(dt.date.today() - dt.timedelta(days=10 * (i + 1))).isoformat(), cats=c, type="demo",
                   text=texts[c[0]], url=None) for i, c in enumerate(cats)]
    from signals import score_events
    sc, counts, neg = score_events(events)
    return dict(status=dict(announcements=True, pledge=True, shareholding=True, insider=True),
                events=events, event_score=sc, event_counts=counts, neg_events=neg,
                pledge=0.0 if good else rnd.uniform(0, 30), pledge_chg=0.0 if good else rnd.uniform(-2, 8),
                promoter_chg=rnd.uniform(0.5, 2.5) if good else rnd.uniform(-3, 1.5),
                fii_chg=rnd.uniform(0.5, 2.5) if good else rnd.uniform(-1, 1),
                dii_chg=rnd.uniform(0.3, 2) if good else rnd.uniform(-1, 1),
                pit_net_cr=rnd.uniform(0.5, 4) if good else rnd.uniform(-3, 1), pit_buys=2 if good else 0, pit_sells=0)


def demo_diligence(ctx):
    n = int(ctx["ticker"][4:6])
    verdict = "red" if n % 11 == 0 else ("green" if n % 7 == 0 else "yellow")
    return dict(status="ok", provider="demo", model="synthetic", method="synthetic demo (no AI was called)", date=dt.date.today().isoformat(),
                verdict=verdict, summary="Synthetic due-diligence text for previewing the layout.",
                management="Synthetic management note.", controversies="Synthetic: none found." if verdict != "red" else "Synthetic: pretend SEBI order found.",
                business_update="Synthetic business update.", order_book="Synthetic order book note.",
                strengths=["Synthetic strength"], risks=["Synthetic risk"], sources=["https://example.com/synthetic"])


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="synthetic data, no network")
    ap.add_argument("--max-fetch", type=int, default=150, help="max fundamentals refreshed this run")
    ap.add_argument("--delay", type=float, default=0.8)
    ap.add_argument("--check", metavar="TICKER", help="fetch and print one company's metrics and scores (first-run sanity check)")
    ap.add_argument("--no-notify", action="store_true")
    a = ap.parse_args()
    if a.check:
        return run_check(a.check)
    DATA.mkdir(exist_ok=True)
    (DOCS).mkdir(exist_ok=True)
    today = dt.date.today().isoformat()
    fund_stats = dict(attempted=0, failed=0)

    if a.demo:
        prices, cache, nifty = demo_data()
        universe_n = len(prices)
    else:
        universe = load_universe()
        universe_n = len(universe)
        print(f"Price stage for {universe_n} tickers")
        prices, nifty = fetch_prices_real(universe)
        cache = load_json(CACHE_JSON, {})

    liquid = {k: v for k, v in prices.items()
              if v["turnover_cr"] >= CFG["min_turnover_cr"] and v["price"] >= CFG["min_price"]}
    print(f"Liquid candidates: {len(liquid)} of {len(prices)} priced")

    if not a.demo:
        cutoff = (dt.date.today() - dt.timedelta(days=CFG["ttl_days"])).isoformat()
        todo = sorted([k for k in liquid if k not in cache or (cache[k].get("fetched") or "") < cutoff],
                      key=lambda k: (k in cache, (cache.get(k) or {}).get("fetched") or ""))[:a.max_fetch]
        print(f"Refreshing fundamentals for {len(todo)} tickers")
        fails = 0
        import signal

        def _stop(signum, frame):
            raise KeyboardInterrupt  # lets the finally block below save progress when the run is cancelled
        try:
            signal.signal(signal.SIGTERM, _stop)
        except Exception:
            pass
        try:
            for i, tk in enumerate(todo, 1):
                fund_stats["attempted"] += 1
                try:
                    cache[tk] = fetch_fund_real(tk)
                    fails = 0
                except Exception as e:
                    msg = str(e)
                    if any(w in msg for w in ("404", "Not Found", "No data found", "delisted")):
                        # genuinely unknown to Yahoo: park it for a week instead of retrying every run
                        cache[tk] = dict(failed=True, error=msg[:80], fetched=today)
                        continue
                    fails += 1
                    fund_stats["failed"] += 1
                    print(f"  {tk} failed: {str(e)[:80]}")
                    if fails >= 15:
                        print("Too many consecutive failures (likely rate-limited); stopping early.")
                        break
                if i % 10 == 0:
                    print(f"  fundamentals {i}/{len(todo)}")
                    save_json(CACHE_JSON, cache)
        finally:
            save_json(CACHE_JSON, cache)
            time.sleep(a.delay)
        save_json(CACHE_JSON, cache)

    # ---- score (pass 1: price + fundamentals only)
    neg_detail = []

    def evaluate(sigs):
        neg_detail.clear()
        scored_, rejected_ = [], {}
        for tk, t in liquid.items():
            f = cache.get(tk)
            if not f or f.get("failed"):
                continue
            m = {**f, **{k: v for k, v in t.items() if k != "spark"}}
            m["nifty_6m"] = nifty["ret_6m"] if nifty else None
            m.update({k: v for k, v in (sigs.get(tk) or {}).items() if k != "status"})
            pil = score_pillars(m)
            sc = composite(pil)
            fl = red_flags(m)
            ok, why = eligible(m, pil, fl)
            if sc is None:
                continue
            if not ok:
                rejected_[why] = rejected_.get(why, 0) + 1
                if why.startswith("negative filing"):
                    bad = [e for e in (m.get("events") or []) if any(c in NEGATIVE for c in e["cats"])][:2]
                    neg_detail.append(dict(ticker=tk, name=m.get("name"), score=round(sc, 1), events=[
                        dict(date=e["date"], labels=[LABELS[c] for c in e["cats"] if c in NEGATIVE], text=e["text"], url=e.get("url")) for e in bad]))
                continue
            scored_.append(dict(ticker=tk, m=m, pil=pil, score=sc, flags=fl, spark=t["spark"]))
        scored_.sort(key=lambda x: -x["score"])
        return scored_, rejected_

    sigs = {}
    scored, rejected = evaluate(sigs)
    print(f"With fundamentals: {sum(1 for k in liquid if k in cache and not cache[k].get('failed'))}; eligible before signals: {len(scored)}")

    # ---- pass 2: event + ownership signals for the strongest candidates
    status = dict(attempted=0, ok={}, blocked=False, checked=0, demo=a.demo)
    top = scored[:CFG["signal_top_n"]]
    if top:
        if a.demo:
            for s_ in top:
                sigs[s_["ticker"]] = demo_signals(s_["ticker"])
        else:
            sig_cache = load_json(SIGNALS_JSON, {})
            debug = load_json(DATA / "signals_debug.json", {})
            client = NSEClient(delay=a.delay)
            print(f"Fetching NSE signals for {len(top)} candidates")
            for s_ in top:
                tk = s_["ticker"]
                c = sig_cache.get(tk)
                if c and c.get("fetched") == today:
                    sigs[tk] = c["data"]
                    continue
                d = fetch_signals(client, tk, debug)
                status["attempted"] += 1
                for k, v in d["status"].items():
                    status["ok"][k] = status["ok"].get(k, 0) + (1 if v else 0)
                sigs[tk] = d
                sig_cache[tk] = dict(fetched=today, data=d)
                if client.blocked:
                    status["blocked"] = True
                    print("NSE appears to be blocking this machine; continuing without further signals.")
                    break
            save_json(SIGNALS_JSON, sig_cache)
            save_json(DATA / "signals_debug.json", dict(debug, updated=today, status=status))
        checked = {tk for tk, d in sigs.items() if any((d.get("status") or {}).values())}
        status["checked"] = len(checked)
        scored, rejected = evaluate(sigs)
        if checked:  # rank only companies whose live signals we actually saw
            scored = [x for x in scored if x["ticker"] in checked]
        print(f"Signals seen for {len(checked)}; eligible after signals: {len(scored)}; rejected: {rejected}")
        for d in neg_detail:
            for e in d["events"]:
                print(f"  NEGATIVE FILING {d['ticker']} {e['date']} [{', '.join(e['labels'])}]: {e['text'][:110]}")

    picks = load_json(PICKS_JSON, [])
    result = dict(generated=today, demo=a.demo, universe=universe_n, liquid=len(liquid),
                  with_data=sum(1 for k in liquid if k in cache and not cache[k].get('failed')), eligible=len(scored), fund_stats=fund_stats,
                  rejected=rejected, signals=status, weights=WEIGHTS, pillar_names=PILLAR_NAMES, verify=VERIFY,
                  pick=None, bench=[], track=[], track_summary={}, dd_rejected=[], dd_blocked=False, dd_provider=None,
                  neg_filing_rejects=neg_detail[:10])

    # ---- stability: keep yesterday's pick unless clearly beaten
    order = list(scored)
    held = False
    if picks and order:
        prev = picks[-1]["ticker"]
        for idx, s_ in enumerate(order[:8]):
            if s_["ticker"] == prev and idx > 0 and order[0]["score"] - s_["score"] < CFG["hysteresis"]:
                order.insert(0, order.pop(idx))
                held = True
                break

    # ---- AI due diligence gate on the finalists
    dd_cache = load_json(DD_JSON, {})
    chosen, chosen_dd, tried = None, None, []
    for s_ in order[:CFG["diligence_top_n"]]:
        ctx = dd_context(s_)
        res = demo_diligence(ctx) if a.demo else diligence.due_diligence(ctx, today, dd_cache)
        tried.append(s_["ticker"])
        if res.get("status") != "ok":          # unavailable or failed: do not block, but say so
            chosen, chosen_dd = s_, res
            break
        result["dd_provider"] = f"{res.get('provider')} / {res.get('model')}"
        if res["verdict"] == "red":
            result["dd_rejected"].append(dict(ticker=s_["ticker"], name=s_["m"].get("name"), score=round(s_["score"], 1),
                                              reason=(res.get("controversies") or res.get("summary") or "")[:300],
                                              sources=res.get("sources", [])[:3]))
            continue
        chosen, chosen_dd = s_, res
        break
    if not a.demo:
        save_json(DD_JSON, dd_cache)
    if chosen is None and order and result["dd_rejected"]:
        result["dd_blocked"] = True
        print("All finalists were rejected by AI due diligence; no pick today.")

    if chosen:
        top = chosen
        m = top["m"]
        streak = 0
        for p in reversed(picks):
            if p["ticker"] == top["ticker"]:
                streak += 1
            else:
                break
        result["pick"] = dict(
            ticker=top["ticker"], name=m.get("name"), sector=m.get("sector"), blurb=m.get("blurb"),
            score=round(top["score"], 1), pillars=top["pil"], flags=top["flags"],
            evidence=build_evidence(m), thesis=build_thesis(m), news=m.get("news") or [],
            events=[dict(date=e["date"], labels=[LABELS[c] for c in e["cats"]], neg=any(c in ("pledge_invoked", "governance", "distress", "regulatory") for c in e["cats"]), text=e["text"], url=e.get("url")) for e in (m.get("events") or [])[:8]],
            diligence=chosen_dd, exit_triggers=exit_triggers(m), held_from_yesterday=held and streak > 0,
            price=m["price"], price_date=m["last_date"], spark=top["spark"], streak=streak + 1,
            mcap_cr=m.get("mcap_cr"), fundamentals_as_of=m.get("fetched"))
        skip = {top["ticker"]} | {d["ticker"] for d in result["dd_rejected"]}
        for s_ in [x for x in order if x["ticker"] not in skip][:CFG["bench"]]:
            mm = s_["m"]
            result["bench"].append(dict(ticker=s_["ticker"], name=mm.get("name"), score=round(s_["score"], 1),
                                        line=build_thesis(mm)[:220], mcap_cr=mm.get("mcap_cr"),
                                        weakest=min(((k, v) for k, v in s_["pil"].items() if v is not None), key=lambda kv: kv[1])[0]))
        last_date = m["last_date"]
        if not a.demo and (not picks or picks[-1]["date"] != last_date):
            picks.append(dict(date=last_date, ticker=top["ticker"], name=m.get("name"),
                              price=m["price"], score=round(top["score"], 1),
                              nifty=nifty["last"] if nifty else None))
            save_json(PICKS_JSON, picks)

    # ---- track record (one row per run of identical picks)
    result["track"], result["track_summary"] = track_episodes(picks, prices, nifty)

    save_json(DOCS / "latest.json", result)
    (DOCS / "index.html").write_text(render_page(clean(result)), encoding="utf-8")
    print("Wrote docs/index.html" + (f" | pick: {result['pick']['ticker']} ({result['pick']['score']})" if result["pick"] else " | no pick today"))
    if not a.demo and not a.no_notify:
        try:
            sent = notify.send(clean(result))
            if sent:
                print("Notified via", ", ".join(sent))
        except Exception as e:
            print("Notification failed:", str(e)[:100])


def run_check(tk):
    """Fetch one company and print everything the scanner would use. Use this on your first real run."""
    if not tk.upper().endswith((".NS", ".BO")) and not tk.upper().startswith("DEMO"):
        tk += ".NS"
    if tk.upper().startswith("DEMO"):
        prices, funds, nifty = demo_data()
        t, f = prices[tk], funds[tk]
    else:
        prices, nifty = fetch_prices_real([tk])
        t = prices.get(tk)
        if not t:
            sys.exit(f"No price history for {tk}. Check the symbol on finance.yahoo.com.")
        f = fetch_fund_real(tk)
    m = {**f, **{k: v for k, v in t.items() if k != "spark"}}
    m["nifty_6m"] = nifty["ret_6m"] if nifty else None
    pil = score_pillars(m)
    fl = red_flags(m)
    print(json.dumps(clean({k: v for k, v in m.items() if k not in ("news", "blurb")}), indent=1))
    print("\nPillars:", {k: (None if v is None else round(v)) for k, v in pil.items()})
    print("Base score (no NSE signals yet):", None if composite(pil) is None else round(composite(pil), 1))
    print("Flags:", [f_["text"] for f_ in fl] or "none")
    ok, why = eligible(m, pil, fl)
    print("Eligible:", ok, why)


if __name__ == "__main__":
    main()
