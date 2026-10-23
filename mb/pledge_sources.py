
"""
Multi-source promoter pledge % resolver.

Tries several free sources, records each result, and reconciles:
  - agreement within TOL_PP → use median, mark source_ok
  - single source only → use it but mark low confidence
  - conflict → pledge stays usable with conflict flag (caller may Watchlist)
  - all fail → None

Sources (in order of preference for *authority*, not fetch order):
  1. nse_pledge_api     — NSE /api/corporate-pledgedata
  2. nse_shp_master     — NSE shareholding master (if pledge field present)
  3. local_cache        — data/pledge_cache.json (manual or weekly job)
  4. env_csv            — path in PLEDGE_CSV (symbol,pledge,as_of)

GitHub Actions often blocks 1–2; 3–4 are the reliability path.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests

from mb.config import DATA, UA
from mb.utils import load_json, save_json

TOL_PP = 1.5  # percentage points: sources "agree" if within this
CACHE_JSON = DATA / "pledge_cache.json"
DEBUG_JSON = DATA / "pledge_sources_debug.json"


def _f(x) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        v = float(str(x).replace("%", "").replace(",", "").strip())
        if v != v or abs(v) > 1000:
            return None
        # XBRL sometimes stores 5049 for 50.49%
        if v > 100:
            v = v / 100.0
        return v
    except (TypeError, ValueError):
        return None


def _find(d: dict, *keys):
    low = {str(k).lower().replace(" ", "").replace("_", ""): v for k, v in d.items()}
    for k in keys:
        kk = k.lower().replace(" ", "").replace("_", "")
        if kk in low and low[kk] not in (None, ""):
            return low[kk]
    for lk, v in low.items():
        for k in keys:
            if k.lower().replace("_", "") in lk and v not in (None, ""):
                return v
    return None


# ---------------------------------------------------------------------------
# Individual sources
# ---------------------------------------------------------------------------

def from_nse_pledge_api(client, sym: str) -> dict[str, Any]:
    """Existing NSE corporate-pledgedata endpoint via NSEClient."""
    raw = client.get("/api/corporate-pledgedata", dict(index="equities", symbol=sym))
    if not raw:
        return dict(ok=False, source="nse_pledge_api", error="no_response")
    rows = raw if isinstance(raw, list) else (raw.get("data") if isinstance(raw, dict) else None)
    if not rows:
        return dict(ok=False, source="nse_pledge_api", error="empty")
    recs = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = _f(_find(r, "percpromotershares", "perc_promoter", "promoter_shares", "encumber", "pledge"))
        if v is None:
            v = _f(_find(r, "percsharescapital", "capital"))
        d = _find(r, "shp_date", "date", "asondate")
        if v is not None:
            recs.append((str(d)[:10] if d else None, v))
    if not recs:
        return dict(ok=False, source="nse_pledge_api", error="no_parse", sample_keys=list(rows[0].keys())[:20] if rows else [])
    recs.sort(key=lambda x: x[0] or "", reverse=True)
    now, chg = recs[0][1], None
    if len(recs) >= 2:
        chg = now - recs[min(4, len(recs) - 1)][1]
    return dict(ok=True, source="nse_pledge_api", pledge=now, pledge_chg=chg, as_of=recs[0][0], n=len(recs))


def from_nse_shareholding_master(client, sym: str) -> dict[str, Any]:
    """Shareholding master — sometimes carries pledge/encumbrance fields."""
    raw = client.get("/api/corporate-share-holdings-master", dict(index="equities", symbol=sym))
    if not raw:
        return dict(ok=False, source="nse_shp_master", error="no_response")
    rows = raw if isinstance(raw, list) else (raw.get("data") if isinstance(raw, dict) else None)
    if not rows or not isinstance(rows, list):
        return dict(ok=False, source="nse_shp_master", error="empty")
    best = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = _f(_find(
            r, "pledge", "pledged", "promoterpledge", "percpledged",
            "encumbered", "promotersharespledged", "totalpledged",
        ))
        if v is None:
            continue
        d = _find(r, "date", "asondate", "shp_date")
        cand = (str(d)[:10] if d else "", v)
        if best is None or cand[0] > best[0]:
            best = cand
    if best is None:
        # Record keys so we can fix parser later
        keys = sorted(rows[0].keys())[:40] if isinstance(rows[0], dict) else []
        return dict(ok=False, source="nse_shp_master", error="no_pledge_field", sample_keys=keys)
    return dict(ok=True, source="nse_shp_master", pledge=best[1], pledge_chg=None, as_of=best[0] or None)


def from_local_cache(sym: str) -> dict[str, Any]:
    """data/pledge_cache.json: { "SYMBOL": {"pledge": 2.1, "as_of": "2026-06-30", "source": "..."} }"""
    cache = load_json(CACHE_JSON, {})
    rec = cache.get(sym) or cache.get(sym.upper()) or cache.get(f"{sym}.NS")
    if not rec:
        return dict(ok=False, source="local_cache", error="not_in_cache")
    v = _f(rec.get("pledge") if isinstance(rec, dict) else rec)
    if v is None:
        return dict(ok=False, source="local_cache", error="bad_value")
    as_of = rec.get("as_of") if isinstance(rec, dict) else None
    return dict(
        ok=True, source="local_cache", pledge=v,
        pledge_chg=_f(rec.get("pledge_chg")) if isinstance(rec, dict) else None,
        as_of=as_of,
        origin=rec.get("source") if isinstance(rec, dict) else None,
    )


def from_env_csv(sym: str) -> dict[str, Any]:
    """Optional CSV at PLEDGE_CSV: columns symbol,pledge,as_of[,pledge_chg]."""
    path = os.environ.get("PLEDGE_CSV") or os.environ.get("PLEDGE_CACHE_CSV")
    if not path or not Path(path).exists():
        return dict(ok=False, source="env_csv", error="no_file")
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                s = (row.get("symbol") or row.get("ticker") or "").replace(".NS", "").strip().upper()
                if s != sym.upper():
                    continue
                v = _f(row.get("pledge") or row.get("pledge_pct"))
                if v is None:
                    return dict(ok=False, source="env_csv", error="bad_value")
                return dict(
                    ok=True, source="env_csv", pledge=v,
                    pledge_chg=_f(row.get("pledge_chg")),
                    as_of=row.get("as_of") or row.get("date"),
                )
    except Exception as e:
        return dict(ok=False, source="env_csv", error=str(e)[:80])
    return dict(ok=False, source="env_csv", error="symbol_not_found")


def from_nse_archives_xbrl_hint(sym: str) -> dict[str, Any]:
    """
    Lightweight: try nsearchives static path patterns are unreliable without
    the filing index. Placeholder records attempt; real XBRL needs prior index.
    Disabled by default unless PLEDGE_TRY_XBRL=1.
    """
    if os.environ.get("PLEDGE_TRY_XBRL") != "1":
        return dict(ok=False, source="nse_xbrl", error="disabled")
    # Without a filing URL we cannot guess; keep as explicit no-op for now
    return dict(ok=False, source="nse_xbrl", error="needs_filing_index")


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------

def resolve_pledge(client, ticker: str, debug: Optional[dict] = None) -> dict[str, Any]:
    """
    Try all sources. Returns:
      pledge, pledge_chg, pledge_source, pledge_as_of, pledge_confidence,
      pledge_sources_tried (list), pledge_conflict (bool)
    """
    sym = ticker.replace(".NS", "").replace(".BO", "").upper()
    tried: list[dict] = []

    for fn in (
        lambda: from_nse_pledge_api(client, sym),
        lambda: from_nse_shareholding_master(client, sym),
        lambda: from_local_cache(sym),
        lambda: from_env_csv(sym),
        lambda: from_nse_archives_xbrl_hint(sym),
    ):
        try:
            res = fn()
        except Exception as e:
            res = dict(ok=False, source=getattr(fn, "__name__", "unknown"), error=str(e)[:80])
        tried.append(res)

    ok_vals = [t for t in tried if t.get("ok") and t.get("pledge") is not None]
    out: dict[str, Any] = {
        "pledge": None,
        "pledge_chg": None,
        "pledge_source": None,
        "pledge_as_of": None,
        "pledge_confidence": "none",
        "pledge_sources_tried": [
            {k: t.get(k) for k in ("source", "ok", "pledge", "as_of", "error") if k in t or t.get(k) is not None}
            for t in tried
        ],
        "pledge_conflict": False,
    }

    if not ok_vals:
        if debug is not None:
            debug.setdefault("pledge_multi", {})[sym] = out["pledge_sources_tried"]
        return out

    values = [float(t["pledge"]) for t in ok_vals]
    sources = [t["source"] for t in ok_vals]

    # Prefer nse_pledge_api if present and no conflict
    primary = None
    for pref in ("nse_pledge_api", "nse_shp_master", "local_cache", "env_csv"):
        for t in ok_vals:
            if t["source"] == pref:
                primary = t
                break
        if primary:
            break
    if primary is None:
        primary = ok_vals[0]

    spread = max(values) - min(values)
    conflict = spread > TOL_PP
    out["pledge_conflict"] = conflict
    if conflict:
        # Median is more robust than first
        vals_sorted = sorted(values)
        mid = vals_sorted[len(vals_sorted) // 2]
        out["pledge"] = mid
        out["pledge_confidence"] = "conflict"
        out["pledge_source"] = "+".join(sources)
        out["pledge_notes"] = f"sources disagree by {spread:.1f}pp: " + ", ".join(
            f"{t['source']}={t['pledge']}" for t in ok_vals
        )
    else:
        out["pledge"] = float(primary["pledge"])
        out["pledge_chg"] = primary.get("pledge_chg")
        out["pledge_source"] = primary["source"]
        out["pledge_as_of"] = primary.get("as_of")
        out["pledge_confidence"] = "high" if len(ok_vals) >= 2 else "single"

    if debug is not None:
        debug.setdefault("pledge_multi", {})[sym] = out["pledge_sources_tried"]
        debug.setdefault("pledge_resolved", {})[sym] = {
            "pledge": out["pledge"],
            "source": out["pledge_source"],
            "confidence": out["pledge_confidence"],
            "conflict": out["pledge_conflict"],
        }

    # Refresh local cache on successful live fetch
    if out["pledge"] is not None and out["pledge_source"] in ("nse_pledge_api", "nse_shp_master"):
        try:
            cache = load_json(CACHE_JSON, {})
            cache[sym] = {
                "pledge": out["pledge"],
                "pledge_chg": out.get("pledge_chg"),
                "as_of": out.get("pledge_as_of") or dt.date.today().isoformat(),
                "source": out["pledge_source"],
                "updated": dt.date.today().isoformat(),
            }
            save_json(CACHE_JSON, cache)
        except Exception:
            pass

    return out


def seed_cache_from_csv(path: str) -> int:
    """Load a CSV into data/pledge_cache.json. Returns rows loaded."""
    n = 0
    cache = load_json(CACHE_JSON, {})
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s = (row.get("symbol") or row.get("ticker") or "").replace(".NS", "").strip().upper()
            v = _f(row.get("pledge") or row.get("pledge_pct"))
            if not s or v is None:
                continue
            cache[s] = {
                "pledge": v,
                "as_of": row.get("as_of") or row.get("date"),
                "source": "csv_import",
                "updated": dt.date.today().isoformat(),
            }
            n += 1
    save_json(CACHE_JSON, cache)
    return n
