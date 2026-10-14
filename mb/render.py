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
.levels{display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-top:8px;font-size:13.5px}
.levels div{display:flex;justify-content:space-between}
.levels .l{color:var(--muted)}
.levels .v{font-weight:700}
.banner{background:var(--soft);border:1px dashed var(--warn);color:var(--warn);border-radius:8px;padding:7px 11px;margin-bottom:11px;font-size:13px;font-weight:600}
"""

def _pct(v):
    if v is None:
        return '<span class="na">n/a</span>'
    return f'<span class="{"pos" if v >= 0 else "neg"}">{v:+.1f}%</span>'


def _multibagger_html(r: dict) -> str:
    pick = r.get("pick")
    h: List[str] = []

    if not pick:
        h.append('<div class="panel"><p>No multibagger pick today.</p></div>')
        return "".join(h)

    m = pick.get("m") or pick
    name = e(str(m.get("name") or pick.get("name") or ""))
    ticker = e(str(pick.get("ticker") or "").replace(".NS", ""))
    score = pick.get("score")
    price = m.get("price")
    thesis = e(str(pick.get("thesis") or m.get("thesis") or "")[:280])

    h.append('<div class="panel">')
    h.append('<div class="row">')
    h.append(f'<div><div class="nm">{name}</div><div class="tk">{ticker} · Multibagger candidate</div></div>')
    if score is not None:
        h.append(f'<div class="score">{score:.0f}<small>score</small></div>')
    h.append("</div>")

    if price:
        h.append(f'<p class="meta">Last ~₹{price} · Longer-term horizon (months+)</p>')

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
    regime = (short_payload or {}).get("regime", "unknown")

    h.append(
        f'<div class="banner">Swing signals · Holding <strong>1–12 trading days</strong> · Regime: {e(str(regime))}</div>'
    )

    if not signals:
        h.append(
            '<div class="panel"><p>No high-confidence swing signals today.</p>'
            '<p class="note">Signals appear when stocks break resistance with volume and clear the confidence filter.</p></div>'
        )
        return "".join(h)

    h.append(
        '<div class="panel"><p class="note">'
        "<strong>How to read:</strong> Buy only if current price is still near Entry. "
        "If price has already run past T1, the signal is stale — skip or trail only. "
        "Always use the Stop Loss. Daily data can lag live prices."
        "</p></div>"
    )

    for s in signals:
        entry = s.get("entry")
        sl = s.get("stop_loss")
        t1 = s.get("t1")
        t2 = s.get("t2")
        t3 = s.get("t3")
        conf = s.get("confidence", 0)
        ticker = e(str(s.get("ticker", "")).replace(".NS", ""))
        last_px = s.get("last_price") or s.get("price")

        status_cls = "fresh"
        status_note = ""
        if last_px and entry and t1:
            if last_px > t1:
                status_cls = "stale"
                status_note = f" · Already past T1 (last ~{last_px})"
            elif last_px > entry * 1.03:
                status_note = f" · Moved up (last ~{last_px})"

        h.append(f'<div class="panel {status_cls}">')
        h.append('<div class="row">')
        h.append(f'<div><div class="nm">{ticker}</div>')
        h.append(f'<div class="tk">Confidence {conf:.0f}/100 · Swing (1–12 days){e(status_note)}</div></div>')
        h.append(f'<div class="score">{conf:.0f}<small>score</small></div>')
        h.append("</div>")

        h.append('<div class="levels">')
        h.append(f'<div><span class="l">Entry (Buy above)</span><span class="v">{entry}</span></div>')
        h.append(f'<div><span class="l">Stop Loss</span><span class="v" style="color:var(--bad)">{sl}</span></div>')
        h.append(f'<div><span class="l">Target 1</span><span class="v" style="color:var(--good)">{t1}</span></div>')
        h.append(f'<div><span class="l">Target 2</span><span class="v" style="color:var(--good)">{t2}</span></div>')
        if t3:
            h.append(f'<div><span class="l">Target 3</span><span class="v" style="color:var(--good)">{t3}</span></div>')
        rr = s.get("risk_reward_t1")
        if rr:
            h.append(f'<div><span class="l">Risk : Reward</span><span class="v">1 : {rr}</span></div>')
        h.append("</div>")

        reasons = s.get("reasons") or []
        if reasons:
            h.append("<p style='margin-top:8px'><strong>Why</strong></p><ul>")
            for rsn in reasons[:5]:
                h.append(f"<li>{e(str(rsn))}</li>")
            h.append("</ul>")

        inv = s.get("invalidation")
        if inv:
            h.append(f'<p class="note" style="margin-top:6px">Invalidation: {e(str(inv))}</p>')

        h.append("</div>")

    h.append(
        '<div class="panel"><p class="note">'
        "Technical screening only. Daily data can lag — always check live price before acting. "
        "Not investment advice."
        "</p></div>"
    )
    return "".join(h)


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
