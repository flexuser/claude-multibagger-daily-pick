"""
Renders docs/index.html — clean tabbed UI for:
  1. Multibagger daily pick
  2. Swing / Short-term technical signals (1–12 trading days)

Self-contained, mobile-first, no external CSS/JS dependencies.
"""
from __future__ import annotations

from html import escape as e
from typing import Any, Dict, List, Optional

from mb.config import SHORT_JSON
from mb.utils import load_json

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
CSS = """
:root{--bg:#ECF0F2;--surface:#F8FAFB;--ink:#0F1E29;--muted:#5A6B77;--line:#CDD6DC;--accent:#0B5FA5;
--good:#1B7F55;--warn:#B26A00;--bad:#B3261E;--empty:#D8E0E5;--soft:#E2E9ED;
--display:'Avenir Next','Segoe UI',system-ui,sans-serif;--body:system-ui,-apple-system,'Segoe UI',sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#0E151B;--surface:#16202A;--ink:#E6EDF2;--muted:#93A4B1;--line:#27343F;
--accent:#5DB0F0;--good:#4CC38A;--warn:#E3A33B;--bad:#F2726B;--empty:#26333E;--soft:#1D2A35}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--body)}
.wrap{max-width:720px;margin:0 auto;padding:16px 14px 50px}
h1,h2,h3{font-family:var(--display);margin:0;letter-spacing:-.01em}
h1{font-size:22px;line-height:1.2}h2{font-size:17px;margin:0 0 8px}h3{font-size:14px;margin:12px 0 4px}
.meta{color:var(--muted);font-size:12.5px;margin:3px 0 12px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:13px;margin-bottom:11px}
.row{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.nm{font-family:var(--display);font-weight:700;font-size:20px;line-height:1.15}
.tk{color:var(--muted);font-size:12.5px}
.score{font-family:var(--display);font-weight:700;font-size:36px;line-height:1;text-align:right}
.score small{display:block;font:500 11px var(--body);color:var(--muted);margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
td,th{padding:6px 3px;border-top:1px solid var(--line);vertical-align:top;text-align:left}
th{font-weight:600;color:var(--muted);font-size:12px;border-top:0}
td.val{font-weight:600;white-space:nowrap}
.pos{color:var(--good);font-weight:600}.neg{color:var(--bad);font-weight:600}
.note{color:var(--muted);font-size:12px}
.chip{display:inline-block;font-weight:700;font-size:11.5px;border:1px solid currentColor;border-radius:5px;padding:1px 7px}
.chip.green{color:var(--good)}.chip.yellow{color:var(--warn)}.chip.red{color:var(--bad)}.chip.none{color:var(--muted)}
ul{margin:5px 0 0;padding-left:18px}li{margin:3px 0}
a{color:var(--accent)}
.tabs{display:flex;gap:0;margin-bottom:14px;border-bottom:2px solid var(--line)}
.tab{flex:1;text-align:center;padding:10px 6px;font-weight:600;font-size:14px;color:var(--muted);cursor:pointer;border:none;background:none;font-family:var(--body)}
.tab.active{color:var(--accent);border-bottom:2px solid var(--accent);margin-bottom:-2px}
.tab-panel{display:none}.tab-panel.active{display:block}
.stale{background:var(--soft);border-left:3px solid var(--warn)}
.fresh{border-left:3px solid var(--good)}
.stale{border-left:3px solid var(--warn);opacity:.92}
.levels{display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-top:8px;font-size:13.5px}
.levels div{display:flex;justify-content:space-between;align-items:center}
.levels .l{color:var(--muted)}
.levels .v{font-weight:700}
.tgt-hit{background:rgba(27,127,85,.15);border-radius:6px;padding:2px 6px}
.tgt-hit.t1{color:var(--good);border:1px solid var(--good)}
.tgt-hit.t2{color:#0d9488;border:1px solid #0d9488}
.tgt-hit.t3{color:#ca8a04;border:1px solid #ca8a04}
.tgt-miss{opacity:.55}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px}
@media(max-width:520px){.stats-grid{grid-template-columns:repeat(2,1fr)}}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 8px;text-align:center}
.stat .n{font-family:var(--display);font-weight:700;font-size:22px;line-height:1.1}
.stat .l{font-size:11px;color:var(--muted);margin-top:2px}
.stat.win .n{color:var(--good)}
.stat.loss .n{color:var(--bad)}
details.hist{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px 13px;margin-bottom:11px}
details.hist summary{cursor:pointer;font-weight:600;font-size:14px;list-style:none}
details.hist summary::-webkit-details-marker{display:none}
details.hist summary::before{content:"▸ ";color:var(--muted)}
details.hist[open] summary::before{content:"▾ "}
.compact-table td,.compact-table th{padding:5px 4px;font-size:12.5px}
.badge{display:inline-block;font-size:10.5px;font-weight:700;border-radius:4px;padding:1px 5px;margin-left:4px}
.badge.ok{background:rgba(27,127,85,.18);color:var(--good)}
.badge.bad{background:rgba(179,38,30,.15);color:var(--bad)}
.badge.exp{background:var(--soft);color:var(--muted)}
.banner{background:var(--soft);border:1px dashed var(--warn);color:var(--warn);border-radius:8px;padding:7px 11px;margin-bottom:11px;font-size:13px;font-weight:600}
"""

def _pct(v):
    if v is None:
        return '<span class="na">n/a</span>'
    return f'<span class="{"pos" if v >= 0 else "neg"}">{v:+.1f}%</span>'


def _watchlist_html(r: dict) -> str:
    """Near-misses: could be next shortlist if listed gaps are resolved."""
    wl = r.get("watchlist") or []
    if not wl:
        return ""
    h: List[str] = []
    h.append('<div class="panel">')
    h.append("<h2>Watchlist — close, but not shortlist yet</h2>")
    h.append(
        '<p class="note">These names clear most gates but are missing specific evidence. '
        "Not a buy list. Resolve the gaps before treating as research shortlist.</p>"
    )
    h.append("<table><tr><th>Stock</th><th>ROCE</th><th>Sales CAGR</th><th>PE</th><th>Missing / what must change</th></tr>")
    for w in wl[:10]:
        tk = e(str(w.get("ticker") or "").replace(".NS", ""))
        name = e(str(w.get("name") or tk)[:28])
        gaps = w.get("needs") or w.get("gaps") or []
        gap_txt = e("; ".join(str(g) for g in gaps[:4]) or "see coverage")
        roce = w.get("roce")
        cagr = w.get("rev_cagr")
        pe = w.get("pe")
        h.append(
            f"<tr><td><strong>{tk}</strong><br><span class='note'>{name}</span></td>"
            f"<td>{'' if roce is None else f'{roce:.0f}%'}</td>"
            f"<td>{'' if cagr is None else f'{cagr:.0f}%'}</td>"
            f"<td>{'' if pe is None else f'{pe:.0f}'}</td>"
            f"<td class='note'>{gap_txt}</td></tr>"
        )
    h.append("</table></div>")
    return "".join(h)


def _multibagger_html(r: dict) -> str:
    pick = r.get("pick")
    h: List[str] = []

    if not pick:
        h.append('<div class="panel"><p>No research shortlist name today.</p>')
        h.append(
            '<p class="note">Shortlist requires every mandatory gate. '
            "See Watchlist below for names that are close.</p></div>"
        )
        h.append(_watchlist_html(r))
        return "".join(h)

    m = pick.get("m") or pick
    name = e(str(m.get("name") or pick.get("name") or ""))
    ticker = e(str(pick.get("ticker") or "").replace(".NS", ""))
    score = pick.get("score")
    price = m.get("price")
    thesis = e(str(pick.get("thesis") or m.get("thesis") or "")[:280])

    h.append('<div class="panel">')
    h.append('<div class="row">')
    h.append(f'<div><div class="nm">{name}</div><div class="tk">{ticker} · Research shortlist (not a buy call)</div></div>')
    if score is not None:
        h.append(f'<div class="score">{score:.0f}<small>score</small></div>')
    h.append("</div>")

    if price is not None:
        try:
            price_fmt = f"{float(price):,.2f}"
        except (TypeError, ValueError):
            price_fmt = str(price)
        h.append(f'<p class="meta">Last ~₹{price_fmt} · Longer-term horizon (months+)</p>')

    if pick.get('disclaimer') or True:
        h.append('<p class="note">Research shortlist only — not a buy call, target, or portfolio instruction. Thresholds are research-policy hypotheses until Phase 2 validation.</p>')
    if thesis:
        h.append(f'<p>{thesis}</p>')

    pillars = pick.get("pillars") or {}
    if pillars:
        h.append("<table style='margin-top:8px'>")
        for k, v in list(pillars.items())[:6]:
            if v is None:
                continue
            h.append(f"<tr><th>{e(str(k))}</th><td class='val'>{v:.0f}</td></tr>")
        h.append("</table>")

    dd = pick.get("dd") or r.get("dd") or {}
    if dd.get("verdict"):
        v = dd["verdict"]
        h.append(f'<p style="margin-top:10px">AI diligence: <span class="chip {v}">{v.upper()}</span></p>')
        if dd.get("summary"):
            h.append(f'<p class="note">{e(str(dd["summary"])[:220])}</p>')

    h.append("</div>")

    track = r.get("track") or []
    if track:
        h.append('<div class="panel"><h2>Track record</h2>')
        h.append("<table><tr><th>Date</th><th>Stock</th><th>Return</th><th>vs Nifty</th></tr>")
        for t in track[:6]:
            h.append(
                f"<tr><td>{e(str(t.get('start','')))}</td>"
                f"<td>{e(str(t.get('ticker','')).replace('.NS',''))}</td>"
                f"<td>{_pct(t.get('ret'))}</td>"
                f"<td>{_pct(t.get('nifty_ret'))}</td></tr>"
            )
        h.append("</table></div>")

    h.append(
        '<div class="panel"><p class="note">'
        "Screening aid only — not investment advice. Most early-stage picks fail. "
        "Do your own research and size positions small."
        "</p></div>"
    )
    return "".join(h)


def _swing_html(short_payload: Optional[dict]) -> str:
    h: List[str] = []
    signals = (short_payload or {}).get("signals") or []
    history = (short_payload or {}).get("history") or []
    stats = (short_payload or {}).get("stats") or {}
    regime = (short_payload or {}).get("regime", "unknown")
    today = (short_payload or {}).get("date") or ""

    h.append(
        f'<div class="banner">Swing · Hold <strong>1–12 trading days</strong> · Regime: {e(str(regime))} · Max 3 picks/day</div>'
    )

    # ----- Accuracy dashboard -----
    closed = int(stats.get("closed") or 0)
    wr = stats.get("win_rate")
    avg_r = stats.get("avg_r")
    t1_hits = int(stats.get("t1_hits") or 0)
    stopped = int(stats.get("stopped") or 0)
    expired = int(stats.get("expired") or 0)
    active_all = [s for s in history if s.get("status") == "active"]
    active_prev = [s for s in active_all if s.get("date") != today]

    h.append('<div class="stats-grid">')
    wr_txt = f"{wr}%" if wr is not None else "—"
    wr_cls = "win" if (wr or 0) >= 50 else ("loss" if wr is not None else "")
    h.append(f'<div class="stat {wr_cls}"><div class="n">{wr_txt}</div><div class="l">Hit rate</div></div>')
    h.append(f'<div class="stat"><div class="n">{avg_r if avg_r is not None else "—"}</div><div class="l">Avg R</div></div>')
    h.append(f'<div class="stat win"><div class="n">{t1_hits}</div><div class="l">Targets hit</div></div>')
    h.append(f'<div class="stat"><div class="n">{len(active_prev)}</div><div class="l">Open calls</div></div>')
    h.append("</div>")
    if closed:
        h.append(
            f'<p class="note" style="margin:-4px 0 12px">Based on <strong>{closed}</strong> closed signals · '
            f'Stopped {stopped} · Expired {expired}. Hit rate = T1/T2/T3 before stop.</p>'
        )

    # ----- Today's signals (max 3) -----
    h.append("<h2 style='margin:4px 0 8px'>Today's top 3</h2>")
    if not signals:
        h.append(
            '<div class="panel"><p>No high-confidence swing signals today. '
            "Volume + breakout + not-already-extended filters are strict.</p></div>"
        )
    else:
        h.append(
            '<div class="panel"><p class="note">'
            "<strong>Rule:</strong> Act only if <em>live</em> price is still near Entry. "
            "If last close already past T1, skip. Always use Stop Loss."
            "</p></div>"
        )
        for s in signals[:3]:
            h.append(_signal_card(s, is_today=True))

    # ----- Open calls (compact table, not full cards) -----
    if active_prev:
        h.append("<h2 style='margin:16px 0 8px'>Open calls</h2>")
        h.append('<div class="panel"><table class="compact-table">')
        h.append(
            "<tr><th>Stock</th><th>Entry</th><th>Now</th><th>SL</th><th>T1</th><th>Day</th><th>Status</th></tr>"
        )
        for s in sorted(active_prev, key=lambda x: -(x.get("confidence") or 0)):
            tk = e(str(s.get("ticker", "")).replace(".NS", ""))
            day = s.get("days_held", 0)
            outcome = s.get("outcome")
            last_px = s.get("last_price")
            now_cell = f"{float(last_px):,.2f}" if last_px is not None else "—"
            if outcome == "t1_hit":
                status = '<span class="badge ok">T1✓</span>'
            elif outcome == "t2_hit":
                status = '<span class="badge ok">T2✓</span>'
            elif outcome == "t3_hit":
                status = '<span class="badge ok">T3✓</span>'
            else:
                status = f"Day {day}"
            t1_cell = _tgt_cell(s.get("t1"), s.get("hit_t1") or outcome in ("t1_hit", "t2_hit", "t3_hit"), "t1")
            h.append(
                f"<tr><td><strong>{tk}</strong></td>"
                f"<td>{s.get('entry')}</td>"
                f"<td>{now_cell}</td>"
                f"<td class='neg'>{s.get('stop_loss')}</td>"
                f"<td>{t1_cell}</td>"
                f"<td>{day}</td>"
                f"<td>{status}</td></tr>"
            )
        h.append("</table></div>")

    # ----- History (collapsible) -----
    closed_list = [
        s for s in history
        if s.get("status") in ("stopped", "target_hit", "expired")
    ]
    closed_list = sorted(
        closed_list,
        key=lambda x: x.get("exit_date") or x.get("date") or "",
        reverse=True,
    )[:20]
    if closed_list or closed:
        h.append('<details class="hist">')
        h.append(
            f"<summary>Track record · {closed} closed · "
            f"Hit rate {wr_txt}</summary>"
        )
        h.append('<table class="compact-table" style="margin-top:8px">')
        h.append(
            "<tr><th>Date</th><th>Stock</th><th>Result</th><th>R</th><th>Days</th>"
            "<th>T1</th><th>T2</th><th>T3</th></tr>"
        )
        for s in closed_list:
            tk = e(str(s.get("ticker", "")).replace(".NS", ""))
            outcome = s.get("outcome") or s.get("status") or ""
            label = {
                "t1_hit": '<span class="badge ok">T1 hit</span>',
                "t2_hit": '<span class="badge ok">T2 hit</span>',
                "t3_hit": '<span class="badge ok">T3 hit</span>',
                "stopped": '<span class="badge bad">Stopped</span>',
                "expired": '<span class="badge exp">Expired</span>',
            }.get(outcome, e(str(outcome)))
            r_mult = s.get("r_multiple")
            r_str = f"{r_mult:+.2f}R" if r_mult is not None else "—"
            r_cls = "pos" if (r_mult or 0) > 0 else ("neg" if r_mult is not None else "")
            h.append(
                f"<tr><td>{e(str(s.get('date','')))}</td>"
                f"<td>{tk}</td>"
                f"<td>{label}</td>"
                f"<td class='{r_cls}'>{r_str}</td>"
                f"<td>{s.get('days_held', '—')}</td>"
                f"<td>{'✓' if s.get('hit_t1') or outcome in ('t1_hit','t2_hit','t3_hit') else '—'}</td>"
                f"<td>{'✓' if s.get('hit_t2') or outcome in ('t2_hit','t3_hit') else '—'}</td>"
                f"<td>{'✓' if s.get('hit_t3') or outcome == 't3_hit' else '—'}</td></tr>"
            )
        h.append("</table>")
        h.append(
            '<p class="note" style="margin-top:8px">'
            "Prediction accuracy = % of closed signals that hit at least T1 before stop/expiry. "
            "R = (exit − entry) / (entry − SL)."
            "</p>"
        )
        h.append("</details>")

    # Debug near-misses (only when scanner ran with --debug)
    near = (short_payload or {}).get("near_misses") or []
    counts = (short_payload or {}).get("reject_counts") or {}
    if near or counts:
        h.append('<details class="hist">')
        h.append("<summary>Debug · near-misses (why nothing / few signals)</summary>")
        if counts:
            parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
            h.append(f'<p class="note" style="margin-top:8px">Reject counts: {e(parts)}</p>')
        if near:
            h.append('<table class="compact-table" style="margin-top:6px">')
            h.append("<tr><th>Stock</th><th>Conf</th><th>Why rejected</th><th>Last</th><th>Entry</th></tr>")
            for n in near[:12]:
                tk = e(str(n.get("ticker", "")).replace(".NS", ""))
                h.append(
                    f"<tr><td>{tk}</td>"
                    f"<td>{n.get('confidence')}</td>"
                    f"<td>{e(str(n.get('reject','')))}</td>"
                    f"<td>{n.get('last_price')}</td>"
                    f"<td>{n.get('entry') or '—'}</td></tr>"
                )
            h.append("</table>")
        h.append(
            '<p class="note">near-miss = breakout-ish or mid confidence but failed a gate. '
            "Run with <code>--debug</code> to populate this.</p>"
        )
        h.append("</details>")

    h.append(
        '<div class="panel"><p class="note">'
        "Technical screening only. Daily bars lag live prices — always verify on your broker. "
        "Not investment advice."
        "</p></div>"
    )
    return "".join(h)


def _tgt_cell(val, hit: bool, level: str) -> str:
    if val is None:
        return "—"
    if hit:
        return f'<span class="tgt-hit {level}">{val} ✓</span>'
    return str(val)


def _signal_card(s: dict, is_today: bool = True) -> str:
    """Render one signal card with colour-coded targets if hit."""
    entry = s.get("entry")
    sl = s.get("stop_loss")
    t1 = s.get("t1")
    t2 = s.get("t2")
    t3 = s.get("t3")
    conf = s.get("confidence", 0)
    ticker = e(str(s.get("ticker", "")).replace(".NS", ""))
    outcome = s.get("outcome")
    days = s.get("days_held", 0)
    last_px = s.get("last_price") or s.get("price")
    as_of = s.get("as_of") or ""
    hit_t1 = bool(s.get("hit_t1") or outcome in ("t1_hit", "t2_hit", "t3_hit"))
    hit_t2 = bool(s.get("hit_t2") or outcome in ("t2_hit", "t3_hit"))
    hit_t3 = bool(s.get("hit_t3") or outcome == "t3_hit")
    # Also infer from last price vs targets
    if last_px and t1 and last_px >= t1:
        hit_t1 = True
    if last_px and t2 and last_px >= t2:
        hit_t2 = True
    if last_px and t3 and last_px >= t3:
        hit_t3 = True

    status_cls = "fresh"
    status_note = ""
    if last_px and t1 and last_px >= t1:
        status_cls = "stale"
        status_note = f" · STALE last ~{last_px} (past T1)"
    elif last_px:
        status_note = f" · last ~{last_px}"
    if as_of:
        status_note += f" as of {as_of}"
    if not is_today:
        status_note += f" · Day {days}"

    parts = [f'<div class="panel {status_cls}">']
    parts.append('<div class="row">')
    parts.append(f'<div><div class="nm">{ticker}</div>')
    conf_txt = f"Confidence {conf:.0f}/100 · " if conf else ""
    parts.append(f'<div class="tk">{conf_txt}Swing (1–12 days){e(status_note)}</div></div>')
    if conf:
        parts.append(f'<div class="score">{conf:.0f}<small>score</small></div>')
    parts.append("</div>")

    parts.append('<div class="levels">')
    # Entry + live/last price side by side for instant context
    entry_txt = str(entry) if entry is not None else "—"
    if last_px is not None:
        try:
            px_f = float(last_px)
            en_f = float(entry) if entry is not None else None
            delta = ""
            if en_f and en_f > 0:
                pct = (px_f - en_f) / en_f * 100
                delta = f" ({pct:+.1f}%)"
            now_html = f'<span class="v">{px_f:,.2f}{delta}</span>'
        except (TypeError, ValueError):
            now_html = f'<span class="v">{last_px}</span>'
        parts.append(
            f'<div><span class="l">Entry (Buy above)</span><span class="v">{entry_txt}</span></div>'
            f'<div><span class="l">Now (as of {e(str(as_of) or "—")})</span>{now_html}</div>'
        )
    else:
        parts.append(f'<div><span class="l">Entry (Buy above)</span><span class="v">{entry_txt}</span></div>')
    parts.append(f'<div><span class="l">Stop Loss</span><span class="v" style="color:var(--bad)">{sl}</span></div>')

    def tgt_html(label, val, hit, cls):
        if val is None:
            return ""
        if hit:
            return (
                f'<div><span class="l">{label}</span>'
                f'<span class="v tgt-hit {cls}">{val} ✓</span></div>'
            )
        return f'<div><span class="l">{label}</span><span class="v">{val}</span></div>'

    parts.append(tgt_html("Target 1", t1, hit_t1, "t1"))
    parts.append(tgt_html("Target 2", t2, hit_t2, "t2"))
    if t3:
        parts.append(tgt_html("Target 3", t3, hit_t3, "t3"))
    rr = s.get("risk_reward_t1")
    if rr:
        parts.append(f'<div><span class="l">Risk : Reward</span><span class="v">1 : {rr}</span></div>')
    parts.append("</div>")

    reasons = s.get("reasons") or []
    if reasons and is_today:
        parts.append("<p style='margin-top:8px'><strong>Why</strong></p><ul>")
        for rsn in reasons[:5]:
            parts.append(f"<li>{e(str(rsn))}</li>")
        parts.append("</ul>")

    inv = s.get("invalidation")
    if inv and is_today:
        parts.append(f'<p class="note" style="margin-top:6px">Invalidation: {e(str(inv))}</p>')

    parts.append("</div>")
    return "".join(parts)



def render_page(result: dict, short_payload: Optional[dict] = None) -> str:
    """
    Unified tabbed page.
    `result` = multibagger scan result
    `short_payload` = short-term signals (loaded automatically if None)
    """
    if short_payload is None:
        short_payload = load_json(SHORT_JSON, {})

    date = result.get("date") or (short_payload or {}).get("date") or ""
    regime = (result.get("nifty") or {}).get("regime") or (short_payload or {}).get("regime") or ""

    has_short = bool((short_payload or {}).get("signals"))
    has_multi = bool(result.get("pick"))
    default_tab = "swing" if has_short and not has_multi else "multi"

    h: List[str] = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>Scanner — {e(str(date))}</title>",
        f"<style>{CSS}</style></head><body><div class='wrap'>",
        f"<h1>Daily Scanner</h1>",
        f"<p class='meta'>{e(str(date))} · Market regime: <strong>{e(str(regime))}</strong></p>",
        '<div class="tabs">',
        f'<button class="tab {"active" if default_tab=="multi" else ""}" onclick="showTab(\'multi\',this)">Multibagger</button>',
        f'<button class="tab {"active" if default_tab=="swing" else ""}" onclick="showTab(\'swing\',this)">Swing Signals</button>',
        "</div>",
        f'<div id="multi" class="tab-panel {"active" if default_tab=="multi" else ""}">',
        _multibagger_html(result),
        "</div>",
        f'<div id="swing" class="tab-panel {"active" if default_tab=="swing" else ""}">',
        _swing_html(short_payload),
        "</div>",
        """<script>
function showTab(id, btn){
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}
</script>""",
        "</div></body></html>",
    ]
    return "".join(h)


def render_short_page(payload: dict) -> str:
    """Lightweight short-only page (still useful as direct link)."""
    date = payload.get("date", "")
    h = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>Swing Signals — {e(str(date))}</title>",
        f"<style>{CSS}</style></head><body><div class='wrap'>",
        f"<h1>Swing Signals</h1>",
        f"<p class='meta'>{e(str(date))} · <a href='index.html'>Full scanner →</a></p>",
        _swing_html(payload),
        "</div></body></html>",
    ]
    return "".join(h)
