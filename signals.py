"""
Event and ownership signals from NSE's public (undocumented) JSON endpoints.

IMPORTANT: these endpoints are not an official API. They can change, need
browser-like cookies, and are sometimes blocked for cloud IPs (including GitHub
runners). Every fetcher therefore fails soft: a missing source returns None
(never a fake zero), the pillar simply drops out of the score, and the run
records which sources worked in data/signals_debug.json so a broken field name
can be fixed quickly.

Pure functions (classify_announcement, score_events, parse_*) contain the logic
and are unit-testable without any network.
"""
import datetime as dt
import re
import time

import pandas as pd
import requests

BASE = "https://www.nseindia.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

# category -> keywords searched in the announcement type + summary text
CATEGORIES = {
    "order_win": ["bagging", "receiving of orders", "order worth", "purchase order", "work order",
                  "letter of award", "letter of intent", "contract worth", "awarded", "order inflow"],
    "expansion": ["capacity expansion", "expansion", "capex", "new plant", "new facility", "greenfield",
                  "brownfield", "commissioning", "commissioned", "additional capacity", "capacity addition",
                  "debottleneck", "new manufacturing", "setting up", "set up a"],
    "capacity_double": ["double the capacity", "doubling of capacity", "doubling its capacity", "doubling capacity",
                        "2x capacity", "twofold", "increase capacity by 100"],
    "acquisition": ["acquisition", "acquire", "acquires", "acquired", "takeover", "wholly owned subsidiary",
                    "merger", "amalgamation", "scheme of arrangement", "stake in"],
    "export": ["export", "overseas", "international customer", "global customer", "foreign customer"],
    "approval": ["approval", "certification", "qualified", "qualification", "licence", "license",
                 "accreditation", "usfda", "patent", "type approval"],
    "promoter_warrants": ["warrants"],
    "bonus_split": ["bonus", "sub-division", "subdivision", "stock split", "split of equity", "face value split"],
    "buyback": ["buyback", "buy-back", "buy back"],
    "rating_up": ["upgrade", "upgraded"],
    # negatives
    "pledge_invoked": ["invocation", "invoked", "pledge invoked"],
    "governance": ["resignation of statutory auditor", "resignation of auditor", "resignation of chief financial",
                   "resignation of cfo", "fraud", "forensic audit"],
    "distress": ["default", "insolvency", "nclt", "winding up", "debt restructuring", "delay in payment"],
    "regulatory": ["sebi order", "show cause", "penalty", "adjudication order", "search and seizure"],
}
NEGATIVE = {"pledge_invoked", "governance", "distress", "regulatory"}
LABELS = {
    "order_win": "Order win", "expansion": "Expansion", "capacity_double": "Capacity doubling",
    "acquisition": "Acquisition", "export": "Export", "approval": "Approval",
    "promoter_warrants": "Promoter warrants", "bonus_split": "Bonus / split", "buyback": "Buyback",
    "rating_up": "Rating upgrade", "pledge_invoked": "Pledge invoked", "governance": "Governance",
    "distress": "Distress", "regulatory": "Regulatory",
}
POINTS = {"order_win": (14, 3), "expansion": (12, 2), "capacity_double": (14, 1), "acquisition": (10, 1),
          "export": (8, 2), "approval": (6, 2), "promoter_warrants": (10, 1), "bonus_split": (4, 1),
          "buyback": (4, 1), "rating_up": (6, 1)}
NEG_PENALTY = 25


# ------------------------------------------------------------ pure logic
def classify_announcement(desc, text):
    """Return the list of categories an announcement matches."""
    t = f"{desc or ''} {text or ''}".lower()
    cats = [c for c, words in CATEGORIES.items() if any(w in t for w in words)]
    # 'warrants' only counts as a promoter signal when the promoter is mentioned
    if "promoter_warrants" in cats and "promoter" not in t:
        cats.remove("promoter_warrants")
    # 'upgrade' only counts for credit ratings
    if "rating_up" in cats and "rating" not in t:
        cats.remove("rating_up")
    # 'stake in' / 'acquire' also appears in routine promoter disclosures; require a deal-like word
    if "acquisition" in cats and not any(w in t for w in ("acqui", "takeover", "merger", "amalgam", "subsidiary", "arrangement")):
        cats.remove("acquisition")
    return cats


def score_events(events):
    """events: list of dicts with 'cats'. Returns (score 0-100, counts, negatives)."""
    counts = {}
    for ev in events:
        for c in ev["cats"]:
            counts[c] = counts.get(c, 0) + 1
    pts = 0
    for c, (per, cap) in POINTS.items():
        pts += min(counts.get(c, 0), cap) * per
    neg = sum(counts.get(c, 0) for c in NEGATIVE)
    pts -= NEG_PENALTY * min(neg, 2)
    return max(0, min(100, pts)), counts, neg


def _find(d, *needles):
    """First value in dict d whose key contains any needle (case-insensitive)."""
    for k, v in d.items():
        kl = str(k).lower()
        if any(n in kl for n in needles):
            return v
    return None


def _f(x):
    try:
        v = float(str(x).replace(",", "").replace("%", "").strip())
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _date(x):
    if x is None:
        return None
    txt = str(x).strip()
    iso = bool(re.match(r"^\d{4}-\d{2}-\d{2}", txt))
    d = pd.to_datetime(txt, dayfirst=not iso, errors="coerce")
    if pd.isna(d):
        return None
    return d.tz_localize(None) if getattr(d, "tzinfo", None) else d


def parse_announcements(rows, days=120, today=None):
    today = pd.Timestamp(today or dt.date.today())
    out, seen = [], set()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d = _date(r.get("an_dt") or r.get("sort_date") or r.get("date") or r.get("exchdisstime"))
        if d is None or (today - d).days > days or d > today + pd.Timedelta(days=1):
            continue
        desc = str(r.get("desc") or r.get("subject") or "")
        text = str(r.get("attchmntText") or r.get("attchmnttext") or r.get("details") or "")
        cats = classify_announcement(desc, text)
        if not cats:
            continue
        key = (str(d.date()), text[:60] or desc)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(date=str(d.date()), cats=cats, type=desc[:60], text=(text or desc)[:200].strip(),
                        url=str(r.get("attchmntFile") or r.get("attchmntfile") or "") or None))
    out.sort(key=lambda e: e["date"], reverse=True)
    return out


def parse_pledge(rows):
    """Latest % of promoter shares pledged, and its change vs ~1 year earlier."""
    recs = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        v = _f(_find(r, "percpromotershares", "perc_promoter", "promoter_shares", "encumber"))
        if v is None:
            v = _f(_find(r, "percsharescapital", "capital"))
        d = _date(_find(r, "shp_date", "date", "asondate"))
        if v is not None:
            recs.append((d, v))
    if not recs:
        return None, None
    recs = sorted(recs, key=lambda x: x[0] or pd.Timestamp("1970-01-01"), reverse=True)
    now = recs[0][1]
    chg = None
    if len(recs) >= 2:
        chg = now - recs[min(4, len(recs) - 1)][1]
    return now, chg


def parse_shareholding(rows):
    """Promoter %, change over ~4 quarters, and FII / DII change when the payload carries them."""
    recs = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d = _date(r.get("date") or r.get("asOnDate"))
        recs.append(dict(
            d=d or pd.Timestamp("1970-01-01"),
            promoter=_f(r.get("pr_and_prgrp") or _find(r, "promoter")),
            fii=_f(_find(r, "fii", "fpi", "foreign")),
            dii=_f(_find(r, "dii", "mutual", "domestic inst"))))
    if not recs:
        return {}
    recs.sort(key=lambda x: x["d"], reverse=True)
    old = recs[min(4, len(recs) - 1)]
    out = {}
    for k in ("promoter", "fii", "dii"):
        if recs[0][k] is not None and old[k] is not None and len(recs) >= 2:
            out[k + "_chg"] = recs[0][k] - old[k]
    if recs[0]["promoter"] is not None:
        out["promoter_now"] = recs[0]["promoter"]
    return out


def parse_insider(rows, days=180, today=None):
    """Net market buying (Rs crore) by promoters / directors in the last `days`."""
    today = pd.Timestamp(today or dt.date.today())
    net, buys, sells = 0.0, 0, 0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d = _date(_find(r, "acqtodt", "acqfromdt", "intimdt", "date"))
        if d is None or (today - d).days > days or d > today + pd.Timedelta(days=1):
            continue
        cat = str(_find(r, "personcategory", "category") or "").lower()
        if not any(w in cat for w in ("promoter", "director", "kmp")):
            continue
        mode = str(_find(r, "acqmode", "mode") or "").lower()
        if any(w in mode for w in ("esop", "gift", "inter-se", "inter se", "pledge", "invoc", "revoc", "bonus", "rights")):
            continue
        ttype = str(_find(r, "tdptransactiontype", "transactiontype", "buy/sell") or mode).lower()
        val = _f(_find(r, "secval", "value"))
        if val is None:
            continue
        if any(w in ttype for w in ("buy", "acqui", "purchase")):
            net += val
            buys += 1
        elif any(w in ttype for w in ("sell", "dispos", "sale")):
            net -= val
            sells += 1
    if buys + sells == 0:
        return 0.0, 0, 0
    return net / 1e7, buys, sells


# --------------------------------------------------------------- client
class NSEClient:
    def __init__(self, delay=0.7):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                               "Accept-Language": "en-US,en;q=0.9", "Referer": BASE + "/"})
        self.delay = delay
        self.fail_streak = 0
        self.blocked = False
        self.warm()

    def warm(self):
        try:
            self.s.get(BASE + "/", timeout=20)
            self.s.get(BASE + "/companies-listing/corporate-filings-announcements", timeout=20)
        except Exception:
            pass

    def get(self, path, params):
        if self.blocked:
            return None
        for attempt in range(2):
            try:
                r = self.s.get(BASE + path, params=params, timeout=25)
                if r.status_code in (401, 403):
                    self.warm()
                elif r.status_code == 200 and r.text.strip():
                    self.fail_streak = 0
                    time.sleep(self.delay)
                    return r.json()
            except Exception:
                pass
            time.sleep(1.5)
        self.fail_streak += 1
        if self.fail_streak >= 8:
            self.blocked = True
        return None


def fetch_signals(client, ticker, debug):
    """Fetch every signal source for one ticker. Missing sources stay None."""
    sym = ticker.replace(".NS", "").replace(".BO", "")
    today = dt.date.today()
    frm = (today - dt.timedelta(days=125)).strftime("%d-%m-%Y")
    to = today.strftime("%d-%m-%Y")
    out = dict(status={})

    def src(name, path, params, parser):
        raw = client.get(path, params)
        ok = raw is not None
        out["status"][name] = ok
        if not ok:
            return None
        rows = raw if isinstance(raw, list) else (raw.get("data") if isinstance(raw, dict) else None)
        res = parser(rows)
        if rows and isinstance(rows[0], dict) and name not in debug:
            debug[name] = sorted(rows[0].keys())[:40]  # record field names for fixing parsers
        return res

    ann = src("announcements", "/api/corporate-announcements",
              dict(index="equities", symbol=sym, from_date=frm, to_date=to), parse_announcements)
    if ann is not None:
        out["events"] = ann
        out["event_score"], out["event_counts"], out["neg_events"] = score_events(ann)
    pl = src("pledge", "/api/corporate-pledgedata", dict(index="equities", symbol=sym), parse_pledge)
    if pl is not None:
        out["pledge"], out["pledge_chg"] = pl
    sh = src("shareholding", "/api/corporate-share-holdings-master", dict(index="equities", symbol=sym), parse_shareholding)
    if sh:
        out.update(sh)
    pit = src("insider", "/api/corporates-pit", dict(index="equities", symbol=sym), parse_insider)
    if pit is not None:
        out["pit_net_cr"], out["pit_buys"], out["pit_sells"] = pit
    return out
