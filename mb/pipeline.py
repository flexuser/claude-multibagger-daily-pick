"""
End-to-end daily scan orchestration.

Stages:
  1. Universe → prices → liquidity filter
  2. Gradual fundamentals refresh (Yahoo)
  3. Score + hard gates
  4. NSE signals for top candidates
  5. Optional nselib delivery enrichment
  6. Hysteresis (keep yesterday unless clearly beaten)
  7. AI due diligence gate
  8. Persist pick + render page + notify
"""
from __future__ import annotations

import datetime as dt
import random
import signal
import time
from typing import Any, Optional

from mb.config import (
    CFG, WEIGHTS, PILLAR_NAMES, VERIFY,
    DATA, DOCS, CACHE_JSON, PICKS_JSON, SIGNALS_JSON, DD_JSON, SIGNALS_DEBUG,
    SHORT_JSON, SWING_HISTORY_JSON,
)
from mb.utils import load_json, save_json, num
from mb.universe import load_universe
from mb.prices import fetch_prices, enrich_delivery
from mb.fundamentals import fetch_fundamentals
from mb.scoring import score_pillars, composite, red_flags, eligible, classify
from mb.evidence import build_evidence, build_thesis, exit_triggers
from mb.context import theme_peer_rs, attach_context
from mb.validate import sanitize_metrics
from mb.signals import NSEClient, fetch_signals, LABELS, NEGATIVE
from mb import diligence
from mb import notify
from mb.render import render_page


# ------------------------------------------------------------------ demo
def demo_data():
    """Synthetic universe so --demo needs no network or keys."""
    random.seed(42)
    prices, cache = {}, {}
    names = [
        ("DEMOA.NS", "Demo Defence Systems", "Defence and aerospace"),
        ("DEMOB.NS", "Demo Specialty Chem", "Specialty chemicals and CDMO"),
        ("DEMOC.NS", "Demo EMS Ltd", "Electronics and semiconductors"),
        ("DEMOD.NS", "Demo Rail Infra", "Railways and infrastructure"),
        ("DEMOE.NS", "Demo Green Energy", "Energy transition"),
    ]
    for i, (tk, name, theme) in enumerate(names):
        base = 80 + i * 30
        prices[tk] = dict(
            price=base + random.uniform(-5, 5),
            last_date=dt.date.today().isoformat(),
            ret_1y=25 + i * 5, ret_6m=12 + i * 2, ret_3m=5 + i,
            above_200dma=8 + i, from_52w_high=-12 + i,
            vol_ratio=1.1 + i * 0.05, turnover_cr=3 + i,
            spark=[base + j for j in range(20)],
            delivery_pct=48 + i * 2,
        )
        cache[tk] = dict(
            name=name, sector=theme, blurb=f"Synthetic {theme} company for demo.",
            themes=[theme], moat_kw=2,
            mcap_cr=1500 + i * 800, revenue_cr=600 + i * 200,
            pe=16 + i, peg=0.8,
            rev_cagr=22 + i * 3, profit_cagr=28 + i * 2,
            op_margin=14 + i, op_margin_chg=1.5, roce=18 + i, roce_chg=1,
            de=0.2, dilution=2, insider_pct=52, inst_pct=12, analysts=3,
            fcf_positive=1, q_rev_yoy=28 + i * 2, q_profit_yoy=35,
            q_opm_chg=1.2, cfo_pat=0.85, interest_coverage=12,
            recv_days=45, recv_days_chg_pct=-5,
            fin_date=(dt.date.today() - dt.timedelta(days=90)).isoformat(),
            q_date=(dt.date.today() - dt.timedelta(days=40)).isoformat(),
            fin_sector="Industrials", capex_rev_pct=8, cwip_growth=40,
            gppe_growth=15, acquisition=False, split_recent=None,
            news=[f"{name} wins new order"], fetched=dt.date.today().isoformat(),
        )
    nifty = dict(last=24000, ret_6m=8.0)
    return prices, cache, nifty


def demo_signals(tk: str) -> dict:
    return dict(
        event_score=35, neg_count=0, events=[],
        promoter_chg=0.5, pledge=2.0, pledge_chg=-0.5,
        fii_chg=1.0, dii_chg=0.5, pit_net_cr=1.2,
        status=dict(announcements=True, shareholding=True, insider=True),
    )


def demo_diligence(ctx: dict) -> dict:
    return dict(
        status="ok", provider="demo", model="synthetic",
        verdict="green",
        summary=f"Synthetic clean diligence for {ctx.get('name')}.",
        management="Synthetic management record clean.",
        management_vision="Synthetic capacity doubling plan over 3 years.",
        controversies="not found",
        business_update="Synthetic order book growing.",
        order_book="Synthetic Rs 800 cr order book.",
        policy_and_demand="Synthetic exposure to structural theme incentives.",
        sector_outlook="Synthetic sector demand healthy.",
        guidance="Synthetic double-digit growth guided.",
        strengths=["Synthetic strength"], risks=["Synthetic risk"],
        sources=["https://example.com/synthetic"],
    )


def dd_context(s_: dict) -> dict:
    m = s_["m"]

    def g(k, d=1, suf=""):
        v = m.get(k)
        return "n/a" if v is None else f"{v:.{d}f}{suf}"

    facts = (
        f"mcap Rs {g('mcap_cr', 0)} cr | rev Rs {g('revenue_cr', 0)} cr | "
        f"rev CAGR {g('rev_cagr', 1)}% | q YoY {g('q_rev_yoy', 1)}% | "
        f"ROCE {g('roce', 1)}% | OPM {g('op_margin', 1)}% | D/E {g('de', 2)} | "
        f"CFO/PAT {g('cfo_pat', 2)}x | pledge {g('pledge', 1)}% | "
        f"RSI {g('rsi_14', 0)} | theme RS {g('theme_rs_6m', 1)} pp | "
        f"news sentiment {g('news_sentiment', 0)}"
    )
    flags = "; ".join(f["text"] for f in s_.get("flags") or [])
    events = "; ".join(
        f"{e.get('date', '')} {e.get('text', '')[:80]}"
        for e in (m.get("events") or [])[:5]
    )
    return dict(
        ticker=s_["ticker"], name=m.get("name"), sector=m.get("sector"),
        mcap_cr=m.get("mcap_cr"), facts=facts, flags=flags, events=events,
        themes=", ".join(m.get("themes") or []),
        regime=m.get("market_regime") or "n/a",
    )


def track_episodes(picks: list, prices: dict, nifty: Optional[dict]) -> tuple[list, dict]:
    """
    Collapse consecutive same-ticker picks into episodes.
    Returns rows the render page expects: start, ticker, name, days, ret, nifty_ret, active.
    """
    if not picks:
        return [], dict(episodes=0, measured=0, beat=0, avg_excess=None)

    episodes = []
    i = 0
    while i < len(picks):
        p = picks[i]
        j = i + 1
        while j < len(picks) and picks[j].get("ticker") == p.get("ticker"):
            j += 1
        entry = p.get("price")
        # Last known price for this ticker in the price dict (if still liquid)
        tk = p.get("ticker")
        last_px = (prices.get(tk) or {}).get("price") if prices else None
        ret = None
        if entry and last_px and entry > 0:
            ret = (last_px / entry - 1) * 100
        nifty_ret = None
        n_entry = p.get("nifty")
        n_last = (nifty or {}).get("last")
        if n_entry and n_last and n_entry > 0:
            nifty_ret = (n_last / n_entry - 1) * 100
        episodes.append(dict(
            start=p.get("date"),
            ticker=tk,
            name=p.get("name"),
            days=j - i,
            ret=ret,
            nifty_ret=nifty_ret,
            active=(j == len(picks)),
        ))
        i = j

    measured = [e for e in episodes if e.get("ret") is not None and e.get("nifty_ret") is not None]
    beat = sum(1 for e in measured if (e["ret"] or 0) > (e["nifty_ret"] or 0))
    excesses = [(e["ret"] - e["nifty_ret"]) for e in measured if e["ret"] is not None and e["nifty_ret"] is not None]
    summary = dict(
        episodes=len(episodes),
        measured=len(measured),
        beat=beat,
        avg_excess=(sum(excesses) / len(excesses)) if excesses else None,
    )
    return episodes, summary


# ------------------------------------------------------------------ main
def run(
    demo: bool = False,
    max_fetch: int = 150,
    delay: float = 0.8,
    no_notify: bool = False,
) -> dict:
    DATA.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)
    today = dt.date.today().isoformat()
    fund_stats = dict(attempted=0, failed=0)

    if demo:
        prices, cache, nifty = demo_data()
        universe_n = len(prices)
    else:
        universe = load_universe()
        universe_n = len(universe)
        print(f"Price stage for {universe_n} tickers")
        prices, nifty = fetch_prices(universe)
        cache = load_json(CACHE_JSON, {})

    liquid = {
        k: v for k, v in prices.items()
        if v["turnover_cr"] >= CFG["min_turnover_cr"] and v["price"] >= CFG["min_price"]
    }
    print(f"Liquid candidates: {len(liquid)} of {len(prices)} priced")

    if not liquid:
        result = dict(
            generated=today, demo=demo, universe=universe_n, liquid=0,
            with_data=0, eligible=0, fund_stats=fund_stats, rejected={"no liquid names": 1},
            signals=dict(attempted=0, ok={}, blocked=False, checked=0, demo=demo),
            weights=WEIGHTS, pillar_names=PILLAR_NAMES, verify=VERIFY,
            pick=None, bench=[], track=[], track_summary={},
            dd_rejected=[], dd_blocked=False, dd_provider=None, neg_filing_rejects=[],
        )
        short_payload = load_json(SHORT_JSON, {})
        html = render_page(result, short_payload=short_payload)
        (DOCS / "index.html").write_text(html, encoding="utf-8")
        save_json(DOCS / "latest.json", result)
        save_json(DATA / "scan_progress.json", dict(stage="done", date=today))
        print("No liquid candidates; wrote empty page.")
        return result

    if not demo:
        cutoff = (dt.date.today() - dt.timedelta(days=CFG["ttl_days"])).isoformat()
        todo = sorted(
            [k for k in liquid if k not in cache or (cache[k].get("fetched") or "") < cutoff],
            key=lambda k: (k in cache, (cache.get(k) or {}).get("fetched") or ""),
        )[:max_fetch]
        print(f"Refreshing fundamentals for {len(todo)} tickers")
        fails = 0

        def _stop(signum, frame):
            raise KeyboardInterrupt

        try:
            signal.signal(signal.SIGTERM, _stop)
        except Exception:
            pass
        try:
            for i, tk in enumerate(todo, 1):
                fund_stats["attempted"] += 1
                try:
                    cache[tk] = fetch_fundamentals(tk)
                    fails = 0
                except Exception as e:
                    msg = str(e)
                    if any(w in msg for w in ("404", "Not Found", "No data found", "delisted")):
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
                    save_json(DATA / "scan_progress.json", dict(
                        stage="fundamentals", done=i, total=len(todo),
                        date=today, last_ticker=tk,
                    ))
                time.sleep(delay)
        finally:
            save_json(CACHE_JSON, cache)

    # ---- score pass 1
    neg_detail: list = []

    theme_rs_map = theme_peer_rs(liquid, cache)

    def evaluate(sigs: dict) -> tuple[list, dict]:
        neg_detail.clear()
        scored_, rejected_ = [], {}
        for tk, t in liquid.items():
            f = cache.get(tk)
            if not f or f.get("failed"):
                continue
            if t.get("price") is None:
                continue
            m = {**f, **{k: v for k, v in t.items() if k != "spark"}}
            m["ticker"] = tk
            m["nifty_6m"] = nifty["ret_6m"] if nifty else None
            sig = {k: v for k, v in (sigs.get(tk) or {}).items() if k != "status"}
            m.update(sig)
            # signals.py uses neg_events; scoring uses neg_count
            if m.get("neg_count") is None and m.get("neg_events") is not None:
                m["neg_count"] = m["neg_events"]
            if m.get("delivery_pct") is None and t.get("delivery_pct") is not None:
                m["delivery_pct"] = t["delivery_pct"]
            attach_context(m, theme_rs_map, nifty)
            m = sanitize_metrics(m)
            # Merge ownership from signals if present
            if m.get("pledge") is None and (sigs.get(tk) or {}).get("pledge") is not None:
                m["pledge"] = sigs[tk]["pledge"]
            fl = red_flags(m)
            from mb.scoring import classify
            decision = classify(m, fl)
            m["_decision"] = decision
            if decision["outcome"] != "shortlist":
                why = (decision["fail"] or decision["unknown"] or decision["watch"] or ["other"])[0]
                rejected_[why] = rejected_.get(why, 0) + 1
                if "negative" in why:
                    bad = [
                        e for e in (m.get("events") or [])
                        if any(c in NEGATIVE for c in e.get("cats", []))
                    ][:2]
                    neg_detail.append(dict(
                        ticker=tk, name=m.get("name"), score=None,
                        events=[
                            dict(
                                date=e.get("date"),
                                labels=[LABELS[c] for c in e["cats"] if c in NEGATIVE],
                                text=e.get("text"), url=e.get("url"),
                            )
                            for e in bad
                        ],
                    ))
                continue
            pil = score_pillars(m)
            sc = composite(pil)
            if sc is None:
                rejected_["incomplete dimensions"] = rejected_.get("incomplete dimensions", 0) + 1
                continue
            scored_.append(dict(
                ticker=tk, m=m, pil=pil, score=sc, flags=fl, spark=t.get("spark"),
                decision=decision, coverage=decision.get("coverage"),
            ))
        scored_.sort(key=lambda x: -x["score"])
        return scored_, rejected_

    sigs: dict = {}
    # Demo: ownership signals available immediately (no NSE)
    if demo:
        for tk in liquid:
            sigs[tk] = demo_signals(tk)
    scored, rejected = evaluate(sigs)
    print(
        f"With fundamentals: {sum(1 for k in liquid if k in cache and not cache[k].get('failed'))}; "
        f"eligible before signals: {len(scored)}; rejected_sample={list(rejected.items())[:5]}"
    )

    # ---- NSE signals for top candidates (and soft candidates if shortlist empty)
    status = dict(attempted=0, ok={}, blocked=False, checked=0, demo=demo)
    top = scored[: CFG["signal_top_n"]]
    if not top and not demo:
        # Soft pass: rank by coverage of non-ownership fields for signal enrichment
        soft = []
        for tk, trow in liquid.items():
            f = cache.get(tk)
            if not f or f.get("failed"):
                continue
            soft.append(dict(ticker=tk, score=float(f.get("roce") or 0)))
        soft.sort(key=lambda x: -x["score"])
        top = soft[: CFG["signal_top_n"]]
    if top:
        if demo:
            for s_ in top:
                sigs[s_["ticker"]] = demo_signals(s_["ticker"])
        else:
            sig_cache = load_json(SIGNALS_JSON, {})
            debug = load_json(SIGNALS_DEBUG, {})
            client = NSEClient(delay=delay)
            print(f"Fetching NSE signals for {len(top)} candidates")
            for s_ in top:
                tk = s_["ticker"]
                c = sig_cache.get(tk)
                if c and c.get("fetched") == today:
                    sigs[tk] = c["data"]
                    continue
                d = fetch_signals(client, tk, debug)
                status["attempted"] += 1
                for k, v in d.get("status", {}).items():
                    status["ok"][k] = status["ok"].get(k, 0) + (1 if v else 0)
                sigs[tk] = d
                sig_cache[tk] = dict(fetched=today, data=d)
                if getattr(client, "blocked", False):
                    status["blocked"] = True
                    print("NSE appears to be blocking this machine; continuing without further signals.")
                    break
            save_json(SIGNALS_JSON, sig_cache)
            save_json(SIGNALS_DEBUG, dict(debug, updated=today, status=status))

            # Optional delivery enrichment for the same set
            enrich_delivery(prices, [s_["ticker"] for s_ in top], delay=delay)

        checked = {tk for tk, d in sigs.items() if any((d.get("status") or {}).values())}
        status["checked"] = len(checked)
        scored, rejected = evaluate(sigs)
        # Prefer names we actually got live signals for, but if NSE is blocked
        # (or almost nothing came back) keep the fundamentals-only ranking.
        if checked and not status.get("blocked") and len(checked) >= max(3, len(top) // 4):
            filtered = [x for x in scored if x["ticker"] in checked]
            if filtered:
                scored = filtered
        print(
            f"Signals seen for {len(checked)}; eligible after signals: {len(scored)}; "
            f"rejected: {rejected}"
        )
        for d in neg_detail:
            for e in d["events"]:
                print(
                    f"  NEGATIVE FILING {d['ticker']} {e['date']} "
                    f"[{', '.join(e['labels'])}]: {(e.get('text') or '')[:110]}"
                )

    picks = load_json(PICKS_JSON, [])
    result: dict[str, Any] = dict(
        generated=today, demo=demo, universe=universe_n, liquid=len(liquid),
        with_data=sum(1 for k in liquid if k in cache and not cache[k].get("failed")),
        eligible=len(scored), fund_stats=fund_stats, rejected=rejected,
        signals=status, weights=WEIGHTS, pillar_names=PILLAR_NAMES, verify=VERIFY,
        pick=None, bench=[], track=[], track_summary={},
        dd_rejected=[], dd_blocked=False, dd_provider=None,
        neg_filing_rejects=neg_detail[:10],
    )

    # No hysteresis: research shortlist is pure rank of names that passed gates
    order = list(scored)
    held = False

    # ---- AI due diligence gate
    dd_cache = load_json(DD_JSON, {})
    chosen, chosen_dd = None, None
    for s_ in order[: CFG["diligence_top_n"]]:
        ctx = dd_context(s_)
        res = demo_diligence(ctx) if demo else diligence.due_diligence(ctx, today, dd_cache)
        if res.get("status") != "ok":
            chosen, chosen_dd = s_, res
            break
        result["dd_provider"] = f"{res.get('provider')} / {res.get('model')}"
        if res.get("verdict") == "red":
            result["dd_rejected"].append(dict(
                ticker=s_["ticker"], name=s_["m"].get("name"),
                score=round(s_["score"], 1),
                reason=(res.get("controversies") or res.get("summary") or "")[:300],
                sources=res.get("sources", [])[:3],
            ))
            continue
        chosen, chosen_dd = s_, res
        break
    if not demo:
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
        # Format events for the page (labels + neg flag)
        raw_events = m.get("events") or []
        page_events = []
        for ev in raw_events[:12]:
            cats = ev.get("cats") or []
            labels = [LABELS[c] for c in cats if c in LABELS]
            if not labels:
                continue
            page_events.append(dict(
                date=ev.get("date") or "",
                text=(ev.get("text") or "")[:220],
                url=ev.get("url"),
                labels=labels,
                neg=any(c in NEGATIVE for c in cats),
            ))

        result["pick"] = dict(
            ticker=top["ticker"],
            name=m.get("name") or top["ticker"],
            sector=m.get("sector") or "",
            blurb=m.get("blurb") or "",
            score=round(float(top["score"]), 1),
            pillars={k: (None if v is None else round(float(v), 1)) for k, v in top["pil"].items()},
            flags=top["flags"] or [],
            evidence=build_evidence(m),
            thesis=build_thesis(m),
            news=list(m.get("news") or [])[:8],
            exit_triggers=exit_triggers(m),
            events=page_events,
            price=float(m["price"]) if m.get("price") is not None else None,
            price_date=m.get("last_date") or today,
            fundamentals_as_of=m.get("fetched") or today,
            spark=top.get("spark") or [],
            diligence=chosen_dd or {},
            streak=int(streak + 1),
            held_from_yesterday=bool(held),
            themes=list(m.get("themes") or []),
            rs_6m=m.get("rs_6m"),
            q_accel=m.get("q_accel"),
        )
        result["bench"] = []
        for s_ in order[1 : 1 + CFG["bench"] + 2]:
            if s_["ticker"] == top["ticker"]:
                continue
            if len(result["bench"]) >= CFG["bench"]:
                break
            mm = s_["m"]
            bits = []
            if mm.get("themes"):
                bits.append(", ".join(mm["themes"][:2]))
            if mm.get("rev_cagr") is not None:
                bits.append(f"rev CAGR {mm['rev_cagr']:.0f}%")
            if mm.get("roce") is not None:
                bits.append(f"ROCE {mm['roce']:.0f}%")
            result["bench"].append(dict(
                ticker=s_["ticker"], name=mm.get("name"),
                score=round(s_["score"], 1), price=mm.get("price"),
                sector=mm.get("sector"),
                line=" · ".join(bits) if bits else (mm.get("sector") or ""),
            ))
        # Log pick
        if not demo:
            entry = dict(
                date=today, ticker=top["ticker"], name=m.get("name"),
                price=m.get("price"), score=round(top["score"], 1),
                nifty=nifty["last"] if nifty else None,
            )
            if not picks or picks[-1].get("date") != today or picks[-1].get("ticker") != top["ticker"]:
                picks.append(entry)
                save_json(PICKS_JSON, picks)

        print(
            f"PICK: {top['ticker']} {m.get('name')} score={top['score']:.1f} "
            f"(streak={streak + 1}, held={held})"
        )
    else:
        print("No pick today.")

    # Immutable daily snapshot (Phase 1 bridge to Phase 2 live validation)
    try:
        from mb.config import RULEBOOK_VERSION, SNAPSHOT_DIR
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        snap = dict(
            date=today,
            rulebook_version=RULEBOOK_VERSION,
            demo=demo,
            shortlist=[
                dict(
                    ticker=s.get("ticker"),
                    score=s.get("score"),
                    coverage=s.get("coverage"),
                    decision=s.get("decision"),
                )
                for s in order[:20]
            ],
            rejected_counts=rejected,
            universe=universe_n,
            liquid=len(liquid),
        )
        from mb.utils import save_json
        save_json(SNAPSHOT_DIR / f"{today}.json", snap)
        result["rulebook_version"] = RULEBOOK_VERSION
        result["outcome_policy"] = (
            "Research shortlist is not a buy call. Thresholds are hypotheses until Phase 2."
        )
    except Exception as e:
        print(f"Snapshot write failed: {e}")

    # Track record
    result["track"], result["track_summary"] = track_episodes(picks, prices, nifty)


    # Render unified tabbed page (includes swing signals if available)
    from mb.config import SHORT_JSON
    short_payload = load_json(SHORT_JSON, {})
    html = render_page(result, short_payload=short_payload)
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    save_json(DOCS / "latest.json", result)
    save_json(DATA / "scan_progress.json", dict(stage="done", date=today))

    if not no_notify and not demo:
        sent = notify.send(result)
        if sent:
            print(f"Notified via {', '.join(sent)}")

    return result


def run_check(tk: str) -> None:
    """Fetch and print one company's metrics and scores (sanity check)."""
    from mb.prices import tech_from_series
    import yfinance as yf
    import logging
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    print(f"=== Check {tk} ===")
    t = yf.Ticker(tk)
    hist = t.history(period="1y", auto_adjust=True)
    tech = tech_from_series(hist["Close"], hist["Volume"]) if len(hist) else None
    fund = fetch_fundamentals(tk)
    m = {**(fund or {}), **(tech or {})}
    pil = score_pillars(m)
    sc = composite(pil)
    fl = red_flags(m)
    ok, why = eligible(m, pil, fl)
    print(f"Name: {m.get('name')} | Sector: {m.get('sector')}")
    print(f"MCap: {m.get('mcap_cr')} cr | Price: {m.get('price')} | Turnover: {m.get('turnover_cr')} cr")
    print(f"Rev CAGR: {m.get('rev_cagr')} | Q YoY: {m.get('q_rev_yoy')} | ROCE: {m.get('roce')} | OPM: {m.get('op_margin')}")
    print(f"D/E: {m.get('de')} | Dilution: {m.get('dilution')} | CFO/PAT: {m.get('cfo_pat')} | Pledge: {m.get('pledge')}")
    print(f"Themes: {m.get('themes')} | Moat kw: {m.get('moat_kw')}")
    print("--- Pillars ---")
    for k, v in pil.items():
        print(f"  {k:12s} {v}")
    print(f"Composite: {sc}")
    print(f"Eligible: {ok}" + (f" ({why})" if not ok else ""))
    print("--- Flags ---")
    for f in fl:
        print(f"  [{f['sev']}] {f['text']}")


# ------------------------------------------------------------------
# Short-term / Swing technical scanner
# ------------------------------------------------------------------
def run_short(
    demo: bool = False,
    max_scan: Optional[int] = None,
    delay: float = 0.6,
    no_notify: bool = False,
    debug: bool = False,
) -> dict:
    """
    Run the short-term technical scanner (1 day – 2 weeks holding).
    Produces BUY above X / SL Y / Targets A-B-C style signals.
    """
    from mb.config import SHORT_TERM, SHORT_JSON, DATA, DOCS
    from mb.short_term import fetch_ohlcv, scan_short_term, generate_signal
    from mb.prices import fetch_prices
    from mb.universe import load_universe
    from mb.render import render_short_page
    import datetime as dt

    today = dt.date.today().isoformat()
    print(f"=== Short-term scanner {today} ===")

    # 1. Market regime
    from mb.prices import _nifty_regime
    nifty = _nifty_regime()
    regime = (nifty or {}).get("regime", "neutral")
    print(f"Market regime: {regime}")

    if demo:
        # Synthetic signals for demo
        signals = [
            {
                "ticker": "DEMOA.NS",
                "signal": "BUY",
                "entry": 312.50,
                "stop_loss": 289.00,
                "t1": 328.00,
                "t2": 345.00,
                "t3": 368.00,
                "confidence": 78.5,
                "holding_days": "3-12 trading days",
                "risk_reward_t1": 1.6,
                "atr": 9.8,
                "rsi": 58.2,
                "volume_surge": 1.9,
                "regime": regime,
                "reasons": ["Breakout above 308.0", "Volume surge 1.90x", "RSI healthy (58.2)", "Above 20 DMA", "Above 50 DMA"],
                "invalidation": "Daily close below 289.00",
                "resistance": 308.0,
                "support": 286.5,
            },
            {
                "ticker": "DEMOB.NS",
                "signal": "BUY",
                "entry": 187.20,
                "stop_loss": 174.50,
                "t1": 196.00,
                "t2": 206.50,
                "t3": 218.00,
                "confidence": 71.0,
                "holding_days": "3-12 trading days",
                "risk_reward_t1": 1.5,
                "atr": 5.4,
                "rsi": 61.4,
                "volume_surge": 1.55,
                "regime": regime,
                "reasons": ["Breakout above 185.0", "Volume surge 1.55x", "RSI healthy (61.4)", "Above 20 DMA"],
                "invalidation": "Daily close below 174.50",
                "resistance": 185.0,
                "support": 172.0,
            },
        ]
        print("Demo mode: 2 synthetic short-term signals generated")
        history = []
        stats = {}
    else:
        # Real scan
        universe = load_universe()
        tickers = [t for t in universe if t.endswith(".NS")][: (max_scan or SHORT_TERM.get("max_scan", 180))]
        print(f"Fetching OHLCV for {len(tickers)} tickers...")
        ohlcv_map = fetch_ohlcv(tickers, period="6mo", interval="1d", delay=delay)
        print(f"Got clean OHLCV for {len(ohlcv_map)} tickers")

        signals = scan_short_term(
            ohlcv_map,
            market_regime=regime,
            cfg=SHORT_TERM,
            debug=debug,
        )
        print(f"Generated {len(signals)} short-term BUY signals (regime={regime})")
        near = getattr(scan_short_term, "last_near_misses", []) or []
        counts = getattr(scan_short_term, "last_reject_counts", {}) or {}
        if counts:
            parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
            print(f"Reject breakdown: {parts}")
        if debug and near:
            print(f"Near-misses (top {min(15, len(near))}):")
            for n in near[:15]:
                print(
                    f"  • {n['ticker']}  conf={n.get('confidence')}  "
                    f"reject={n.get('reject')}  last={n.get('last_price')}  "
                    f"entry={n.get('entry')}  reasons={n.get('reasons')}"
                )
        elif debug:
            print("Near-misses: none (most names had no breakout)")

        # Multi-day history: update previous active signals + add today's
        from mb.short_term import update_swing_history, swing_stats
        from mb.db import load_swing_history, save_swing_history, supabase_enabled
        prev_history = load_swing_history()
        # Also fetch OHLCV for any active tickers not in today's scan
        active_tickers = [s["ticker"] for s in prev_history if s.get("status") == "active"]
        missing = [t for t in active_tickers if t not in ohlcv_map]
        if missing:
            extra = fetch_ohlcv(missing, period="1mo", interval="1d", delay=delay)
            ohlcv_map.update(extra)
        history = update_swing_history(signals, ohlcv_map, today, prev_history)
        save_swing_history(history)  # JSON always; Supabase if env set
        if supabase_enabled():
            print("Swing history backend: Supabase + JSON backup")
        else:
            print("Swing history backend: JSON only (set SUPABASE_URL + SUPABASE_KEY for DB)")
        stats = swing_stats(history)
        print(f"Swing history: {sum(1 for s in history if s.get('status')=='active')} active, "
              f"{stats.get('closed',0)} closed, win_rate={stats.get('win_rate')}%")
    # Persist
    near = getattr(scan_short_term, "last_near_misses", []) or [] if not demo else []
    counts = getattr(scan_short_term, "last_reject_counts", {}) or {} if not demo else {}
    payload = {
        "date": today,
        "regime": regime,
        "nifty": nifty,
        "signals": signals[: SHORT_TERM.get("max_show", 3)],
        "history": history,
        "stats": stats,
        "near_misses": near[:15] if debug else [],
        "reject_counts": counts if debug else {},
        "total_scanned": 0 if demo else len(ohlcv_map) if not demo else 0,
        "mode": "short",
        "debug": debug,
    }
    save_json(SHORT_JSON, payload)
    save_json(DOCS / "short_latest.json", payload)

    # Render short-only page + unified tabbed index
    from mb.render import render_short_page, render_page
    html_short = render_short_page(payload)
    (DOCS / "short.html").write_text(html_short, encoding="utf-8")
    print(f"Wrote docs/short.html with {len(payload['signals'])} signals")

    # Also refresh main index.html so both tabs are available
    multi_result = load_json(DOCS / "latest.json", {})
    if not multi_result:
        multi_result = {"date": today, "pick": None, "track": []}
    html_main = render_page(multi_result, short_payload=payload)
    (DOCS / "index.html").write_text(html_main, encoding="utf-8")
    print("Updated docs/index.html (tabbed view)")

    if not no_notify and not demo and signals:
        try:
            from mb import notify
            # Simple text summary
            lines = [f"Short-term signals ({today}) — regime: {regime}"]
            for s in signals[:5]:
                lines.append(
                    f"• {s['ticker']}  BUY > {s['entry']} | SL {s['stop_loss']} | "
                    f"T1 {s['t1']}  conf {s['confidence']}"
                )
            # Re-use existing notify if possible; otherwise just print
            print("\n".join(lines))
        except Exception:
            pass

    return payload
