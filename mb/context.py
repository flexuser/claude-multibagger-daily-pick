"""
Cross-sectional and soft-context features (still free-tier):

  * Theme / peer relative strength (sector sentiment proxy)
  * Headline news keyword sentiment
  * Policy / PLI keyword hits in news + blurb
  * Market regime adjustment helpers

These never invent data: missing inputs stay None and drop out of averages.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

# Lightweight sentiment lexicons (English headlines from Yahoo / filings text)
POS = {
    "win", "wins", "won", "order", "orders", "bag", "bags", "bagged", "award", "awarded",
    "expand", "expansion", "capacity", "growth", "record", "profit", "surge", "rise",
    "upgrade", "approved", "approval", "contract", "export", "guidance", "strong",
    "beat", "raises", "raised", "commission", "commissioned", "mou", "partnership",
}
NEG = {
    "loss", "losses", "fraud", "sebi", "probe", "investigation", "default", "insolvency",
    "nclt", "resignation", "resigns", "downgrade", "penalty", "show cause", "pledge",
    "invoked", "delay", "miss", "weak", "decline", "fall", "slump", "warning", "qualified",
    "auditor", "litigation", "raid", "search", "seizure", "bankruptcy",
}

# Policy / structural demand keywords (India-focused)
POLICY = {
    "pli", "production linked", "make in india", "atmanirbhar", "defence indigenisation",
    "indigenisation", "capex cycle", "national infrastructure", "green hydrogen",
    "renewable target", "ev policy", "fsr", "production-linked", "semiconductor mission",
    "electronics manufacturing", "railways budget", "defence budget", "export incentive",
    "rodtep", "subsidy", "incentive scheme",
}


def news_sentiment(titles: list[str]) -> Optional[float]:
    """
    Return score 0–100 from recent headline keywords.
    Neutral / empty → None (do not invent sentiment).
    """
    if not titles:
        return None
    pos = neg = 0
    for t in titles:
        low = re.sub(r"[^a-z0-9\s]", " ", (t or "").lower())
        words = set(low.split())
        # multi-word phrases
        if any(p in low for p in ("show cause", "stock split", "bagged order", "order win")):
            if "show cause" in low:
                neg += 2
            else:
                pos += 2
        pos += sum(1 for w in POS if w in words or w in low)
        neg += sum(1 for w in NEG if w in words or w in low)
    total = pos + neg
    if total == 0:
        return 50.0  # neutral headlines
    return round(100.0 * pos / total, 1)


def policy_hits(text: str) -> int:
    t = (text or "").lower()
    return sum(1 for p in POLICY if p in t)


def theme_peer_rs(
    liquid_metrics: dict[str, dict],
    fund_cache: dict[str, dict],
) -> dict[str, float]:
    """
    For each theme, average 6m return of liquid names tagged with that theme.
    Returns ticker → excess vs theme peers (own ret_6m - theme avg ret_6m).
    """
    theme_rets: dict[str, list[float]] = defaultdict(list)
    ticker_themes: dict[str, list[str]] = {}

    for tk, px in liquid_metrics.items():
        f = fund_cache.get(tk) or {}
        if f.get("failed"):
            continue
        themes = f.get("themes") or []
        r = px.get("ret_6m")
        if r is None or not themes:
            continue
        ticker_themes[tk] = themes
        for th in themes:
            theme_rets[th].append(float(r))

    theme_avg = {th: sum(vs) / len(vs) for th, vs in theme_rets.items() if len(vs) >= 3}

    out: dict[str, float] = {}
    for tk, themes in ticker_themes.items():
        r = liquid_metrics[tk].get("ret_6m")
        if r is None:
            continue
        avgs = [theme_avg[th] for th in themes if th in theme_avg]
        if not avgs:
            continue
        peer = sum(avgs) / len(avgs)
        out[tk] = round(float(r) - peer, 2)
    return out


def attach_context(
    m: dict,
    theme_rs_map: dict[str, float],
    nifty: Optional[dict],
) -> None:
    """Mutate metric dict with context fields used by scoring."""
    tk = m.get("ticker")
    if tk and tk in theme_rs_map:
        m["theme_rs_6m"] = theme_rs_map[tk]

    titles = m.get("news") or []
    m["news_sentiment"] = news_sentiment(titles)

    blob = " ".join(
        str(x or "")
        for x in (
            m.get("blurb"),
            m.get("sector"),
            " ".join(titles),
            " ".join(e.get("text", "") for e in (m.get("events") or [])[:8]),
        )
    )
    m["policy_hits"] = policy_hits(blob)

    if nifty:
        m["market_regime"] = nifty.get("regime")
        m["nifty_above_200"] = nifty.get("above_200dma")
        m["nifty_ret_3m"] = nifty.get("ret_3m")
