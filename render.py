"""Renders docs/index.html from the scan result. Self-contained, mobile-first."""
from html import escape as e

CSS = """
:root{--bg:#ECF0F2;--surface:#F8FAFB;--ink:#0F1E29;--muted:#5A6B77;--line:#CDD6DC;--accent:#0B5FA5;
--good:#1B7F55;--warn:#B26A00;--bad:#B3261E;--empty:#D8E0E5;--soft:#E2E9ED;
--display:'Avenir Next','Segoe UI',system-ui,sans-serif;--body:system-ui,-apple-system,'Segoe UI',sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#0E151B;--surface:#16202A;--ink:#E6EDF2;--muted:#93A4B1;--line:#27343F;
--accent:#5DB0F0;--good:#4CC38A;--warn:#E3A33B;--bad:#F2726B;--empty:#26333E;--soft:#1D2A35}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--body)}
.wrap{max-width:720px;margin:0 auto;padding:18px 16px 60px}
h1,h2,h3{font-family:var(--display);margin:0;letter-spacing:-.01em}
h1{font-size:26px;line-height:1.15}h2{font-size:19px;margin:0 0 8px}h3{font-size:15px;margin:14px 0 4px}
.meta{color:var(--muted);font-size:13px;margin:4px 0 14px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:12px}
.banner{background:var(--soft);border:1px dashed var(--warn);color:var(--warn);border-radius:10px;padding:8px 12px;margin-bottom:12px;font-weight:600}
.row{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.nm{font-family:var(--display);font-weight:700;font-size:22px;line-height:1.15}
.tk{color:var(--muted);font-size:13px}
.score{font-family:var(--display);font-weight:700;font-size:44px;line-height:1;text-align:right}
.score small{display:block;font:500 11px var(--body);color:var(--muted);margin-top:3px}
.thesis{margin:12px 0 4px}
svg.spark{width:100%;height:80px;display:block;margin:10px 0 2px}
.pil{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:7px 0;border-top:1px solid var(--line)}
.pil:first-of-type{border-top:0}.pil .v{font-family:var(--display);font-weight:700}
.bar{grid-column:1/-1;height:6px;background:var(--empty);border-radius:3px;overflow:hidden}
.bar span{display:block;height:100%;background:var(--accent)}.bar .g{background:var(--good)}.bar .l{background:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:7px 4px;border-top:1px solid var(--line);vertical-align:top;text-align:left}
th{font-weight:600;color:var(--muted);font-size:12.5px;border-top:0}
td.mk{width:22px;font-weight:700;text-align:center}.ok{color:var(--good)}.no{color:var(--warn)}.na{color:var(--muted)}
td.val{white-space:nowrap;font-weight:600}
.why{display:block;color:var(--muted);font-size:12.5px;font-weight:400}
.grp td{background:var(--soft);font-weight:700;font-size:13px;border-top:1px solid var(--line)}
.flag{padding:6px 0 6px 16px;position:relative;border-top:1px solid var(--line)}
.flag:first-of-type{border-top:0}.flag:before{content:"";position:absolute;left:0;top:13px;width:8px;height:8px;border-radius:50%;background:var(--warn)}
.flag.high:before{background:var(--bad)}
ul{margin:6px 0 0;padding-left:20px}li{margin:4px 0}
.note{color:var(--muted);font-size:12.5px}
.pos{color:var(--good);font-weight:600}.neg{color:var(--bad);font-weight:600}
.scroll{overflow-x:auto}
.chip{display:inline-block;font-weight:700;font-size:12.5px;border:1px solid currentColor;border-radius:6px;padding:2px 9px}
.chip.green{color:var(--good)}.chip.yellow{color:var(--warn)}.chip.red{color:var(--bad)}.chip.none{color:var(--muted)}
.dd h3{margin:12px 0 2px;color:var(--muted);font-size:12.5px;text-transform:uppercase;letter-spacing:.04em}
.dd p{margin:0 0 4px}
a{color:var(--accent);word-break:break-all}
"""


def _band(v):
    return "g" if v is not None and v >= 65 else ("l" if v is not None and v < 40 else "")


def _spark(vals):
    if not vals or len(vals) < 3:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    pts = " ".join(f"{i * 300 / (len(vals) - 1):.1f},{74 - (v - lo) / rng * 68:.1f}" for i, v in enumerate(vals))
    return (f'<svg class="spark" viewBox="0 0 300 80" preserveAspectRatio="none" role="img" aria-label="One year price chart">'
            f'<polyline fill="none" stroke="var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke" points="{pts}"/></svg>')


def _pct(v):
    if v is None:
        return '<span class="na">n/a</span>'
    return f'<span class="{"pos" if v >= 0 else "neg"}">{v:+.1f}%</span>'


def _links(urls):
    out = []
    for u in urls or []:
        if str(u).startswith(("http://", "https://")):
            out.append(f'<li><a href="{e(u)}" rel="noopener noreferrer">{e(u[:70])}</a></li>')
    return "<ul>" + "".join(out) + "</ul>" if out else ""


def _dd_panel(dd):
    if not dd:
        return ""
    if dd.get("status") != "ok":
        label = "unavailable" if dd.get("status") == "unavailable" else "failed"
        return ('<div class="panel"><h2>AI due diligence <span class="chip none">not run</span></h2>'
                f'<p>{e(dd.get("reason", ""))}</p><p class="note">Status: {label}. Until it runs, treat management and litigation risk as unchecked, and read the "Verify before you act" list.</p></div>')
    v = dd["verdict"]
    meaning = {"green": "Nothing adverse found, with some corroboration.", "yellow": "Unresolved concerns or thin information. Read the risks.", "red": "Serious concerns found."}[v]
    h = [f'<div class="panel dd"><h2>AI due diligence <span class="chip {v}">{v.upper()}</span></h2><p class="note">{e(meaning)}</p>',
         f'<p>{e(dd["summary"])}</p>']
    for title, key in (("Management", "management"), ("Controversies and litigation", "controversies"),
                       ("Latest business update", "business_update"), ("Order book, capex, exports", "order_book")):
        if dd.get(key):
            h.append(f'<h3>{title}</h3><p>{e(dd[key])}</p>')
    if dd.get("strengths"):
        h.append("<h3>Strengths</h3><ul>" + "".join(f"<li>{e(x)}</li>" for x in dd["strengths"]) + "</ul>")
    if dd.get("risks"):
        h.append("<h3>Risks</h3><ul>" + "".join(f"<li>{e(x)}</li>" for x in dd["risks"]) + "</ul>")
    if dd.get("sources"):
        h.append("<h3>Sources</h3>" + _links(dd["sources"]))
    h.append(f'<p class="note" style="margin-top:10px">Written by an AI ({e(str(dd.get("provider")))} / {e(str(dd.get("model")))}, {e(str(dd.get("method")))}) on {e(str(dd.get("date")))}. '
             'It can be wrong. Open the sources and confirm anything you rely on. It never changes the score, it only blocks a pick when it finds serious problems.</p></div>')
    return "".join(h)


def render_page(r):
    h = [f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
         f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
         f'<title>Daily multibagger candidate</title><style>{CSS}</style></head><body><div class="wrap">']
    h.append('<h1>Daily multibagger candidate</h1>')
    h.append(f'<p class="meta">Scan of {r["generated"]}. {r["universe"]} stocks in the universe, {r["liquid"]} liquid enough, '
             f'{r["with_data"]} with fundamentals, {r["eligible"]} passed the filters.</p>')
    if r.get("demo"):
        h.append('<div class="banner">DEMO DATA. These are synthetic companies for previewing the layout, not real stocks.</div>')

    p = r.get("pick")
    if not p:
        if r.get("dd_blocked"):
            h.append('<div class="panel"><h2>No pick today</h2><p>The best-scoring candidates were all rejected by AI due diligence, so nothing is shown rather than a stock with serious concerns. See below.</p></div>')
        else:
            h.append('<div class="panel"><h2>No candidate today</h2><p>Nothing passed the hard filters with enough data. '
                     'This is normal while the fundamentals cache is still filling up (each run refreshes a limited batch). '
                     'Run the workflow a few more times, or check the log for failures.</p></div>')
    else:
        streak = f' On top for {p["streak"]} scans in a row.' if p["streak"] > 1 else ' New today.'
        held = " Kept from yesterday because no rival beat it by a clear margin." if p.get("held_from_yesterday") else ""
        dd = p.get("diligence") or {}
        chip = f'<span class="chip {dd["verdict"]}">DD {dd["verdict"].upper()}</span>' if dd.get("status") == "ok" else '<span class="chip none">DD not run</span>'
        h.append('<div class="panel">'
                 f'<div class="row"><div><div class="nm">{e(p["name"] or p["ticker"])}</div>'
                 f'<div class="tk">{e(p["ticker"])} | {e(p.get("sector") or "")}</div><div style="margin-top:6px">{chip}</div></div>'
                 f'<div class="score">{p["score"]:.0f}<small>of 100</small></div></div>'
                 f'{_spark(p.get("spark"))}'
                 f'<div class="tk">Price Rs {p["price"]:,.2f} as of {e(p["price_date"])}. Fundamentals as of {e(p.get("fundamentals_as_of") or "n/a")}.{streak}{held}</div>'
                 f'<p class="thesis">{e(p["thesis"])}</p></div>')

        h.append(_dd_panel(dd))

        h.append('<div class="panel"><h2>Score breakdown</h2>')
        for k, v in p["pillars"].items():
            w = r["weights"][k]
            name = r["pillar_names"][k]
            h.append(f'<div class="pil"><b>{e(name)} <span class="note">weight {w}</span></b>'
                     f'<span class="v">{"n/a" if v is None else round(v)}</span>'
                     f'<div class="bar"><span class="{_band(v)}" style="width:{0 if v is None else v:.0f}%"></span></div></div>')
        h.append('<p class="note">Runway and moat are keyword and ratio proxies, since a scanner cannot read a business the way you can. They carry lower weight for that reason. '
                 'A pillar with no data is left out and the rest are re-weighted.</p></div>')

        h.append('<div class="panel"><h2>Proof</h2><div class="scroll"><table>')
        group = None
        for ev in p["evidence"]:
            if ev["group"] != group:
                group = ev["group"]
                h.append(f'<tr class="grp"><td colspan="3">{e(group)}</td></tr>')
            mk, cls = ("&#10003;", "ok") if ev["ok"] is True else (("&#10007;", "no") if ev["ok"] is False else ("-", "na"))
            h.append(f'<tr><td class="mk {cls}">{mk}</td><td>{e(ev["label"])}<span class="why">{e(ev["why"])}</span></td>'
                     f'<td class="val">{e(str(ev["value"]))}</td></tr>')
        h.append('</table></div></div>')

        evs = p.get("events") or []
        sg = r.get("signals") or {}
        if evs:
            h.append('<div class="panel"><h2>Filings that matter, last 120 days</h2>')
            for ev in evs:
                cls = "neg" if ev["neg"] else "pos"
                link = f' <a href="{e(ev["url"])}" rel="noopener">filing</a>' if ev.get("url") and str(ev["url"]).startswith("http") else ""
                h.append(f'<div class="flag {"high" if ev["neg"] else ""}"><b class="{cls}">{e(", ".join(ev["labels"]))}</b> '
                         f'<span class="note">{e(ev["date"])}</span>{link}<br>{e(ev["text"])}</div>')
            h.append('<p class="note">Matched by keywords on NSE filing summaries. Open each filing to confirm size and terms, since a keyword match can be routine.</p></div>')
        elif sg.get("checked"):
            h.append('<div class="panel"><h2>Filings that matter</h2><p>No expansion, order, acquisition or export filings found in the last 120 days.</p></div>')

        if p["flags"]:
            h.append('<div class="panel"><h2>Red flags</h2>' + "".join(
                f'<div class="flag {f["sev"]}">{e(f["text"])}</div>' for f in p["flags"]) + '</div>')

        if p.get("exit_triggers"):
            h.append('<div class="panel"><h2>What would prove this wrong</h2><p class="note">Write these down before you buy. Check them each quarter.</p><ul>'
                     + "".join(f"<li>{e(t)}</li>" for t in p["exit_triggers"]) + '</ul></div>')

        if p.get("news"):
            h.append('<div class="panel"><h2>Recent headlines</h2><ul>' + "".join(f"<li>{e(n)}</li>" for n in p["news"]) +
                     '</ul><p class="note">Headlines come from Yahoo and can be generic. Read the originals.</p></div>')

        h.append('<div class="panel"><h2>Verify before you act</h2><p>Automated checks cannot settle these. They are often where a promising number turns out to be a trap.</p><ul>'
                 + "".join(f"<li>{e(v)}</li>" for v in r["verify"]) + '</ul></div>')

    if r.get("dd_rejected"):
        h.append('<div class="panel"><h2>Rejected by AI due diligence today</h2>')
        for d in r["dd_rejected"]:
            h.append(f'<h3>{e(d["name"] or d["ticker"])} <span class="tk">{e(d["ticker"])}, score {d["score"]:.0f}</span></h3><p class="note" style="margin:0">{e(d["reason"])}</p>{_links(d.get("sources"))}')
        h.append('<p class="note">These scored higher but the research found serious concerns. Verify before dismissing or trusting that result.</p></div>')

    if p and r["bench"]:
        h.append('<div class="panel"><h2>Next in line</h2><p class="note">Not yet due-diligenced.</p>')
        for b in r["bench"]:
            h.append(f'<h3>{e(b["name"] or b["ticker"])} <span class="tk">{e(b["ticker"])}, score {b["score"]:.0f}</span></h3>'
                     f'<p class="note" style="margin:0">{e(b["line"])}</p>')
        h.append('</div>')

    ts = r.get("track_summary") or {}
    if r["track"]:
        h.append('<div class="panel"><h2>Track record</h2>')
        if ts.get("measured"):
            ex = ts.get("avg_excess")
            h.append(f'<p>{ts["episodes"]} picks so far. {ts["beat"]} of {ts["measured"]} beat the Nifty since being picked'
                     + (f', average edge {ex:+.1f} pp' if ex is not None else '') + '.</p>')
        h.append('<div class="scroll"><table><tr><th>Picked</th><th>Stock</th><th>Days on top</th><th>Since pick</th><th>Nifty</th></tr>')
        for t in r["track"]:
            h.append(f'<tr><td>{e(t["start"])}</td><td>{e(t["name"] or t["ticker"])}{" (now)" if t.get("active") else ""}</td><td>{t["days"]}</td>'
                     f'<td>{_pct(t["ret"])}</td><td>{_pct(t["nifty_ret"])}</td></tr>')
        h.append('</table></div><p class="note">One row per run of the same pick, logged at its scan-day price. Judge the scanner by this table over many months and at least 20 picks, not by any single result. '
                 'The score weights are reasoned starting points, not fitted to history, so this record is the real test.</p></div>')

    sg = r.get("signals") or {}
    if sg.get("demo"):
        cov = "Demo mode: signals are synthetic."
    elif sg.get("checked"):
        parts = ", ".join(f"{k} {v}/{sg['attempted']}" for k, v in (sg.get("ok") or {}).items()) if sg.get("attempted") else "reused from today's cache"
        cov = f"Live NSE signals seen for {sg['checked']} candidates ({parts})." + (" NSE started blocking midway." if sg.get("blocked") else "")
    else:
        cov = "NSE signals were NOT available today (blocked or changed). Ranking uses price and fundamentals only, so ownership and catalyst pillars are missing."
    fs = r.get("fund_stats") or {}
    health = f" Fundamentals refreshed this run: {fs.get('attempted', 0)} tried, {fs.get('failed', 0)} failed." if fs.get("attempted") else ""
    rej = ", ".join(f"{k}: {v}" for k, v in (r.get("rejected") or {}).items()) or "none"
    h.append(f'<div class="panel"><h2>How it works</h2><p>Every liquid NSE small, mid and micro cap is scored on ten pillars: runway, moat, proof, operating leverage, '
             f'capital and earnings quality, discovery stage, valuation, market confirmation, ownership and catalysts. Hard filters remove financial companies, stale or suspect data, tiny or huge companies, '
             f'unprofitable or slow-growing ones, high pledge, negative filings, and multiple red flags. The finalists then get AI due diligence, and a red verdict blocks the pick. Filtered out today: {e(rej)}.</p>'
             f'<p class="note">Signal coverage: {e(cov)} Event and ownership data is fetched only for the 40 strongest candidates each day.{e(health)}</p>'
             '<p class="note">A screening aid, not investment advice. Most early-stage picks fail, free data can be wrong, and a high score only means the evidence lines up with the story. '
             'Do your own research and size positions small.</p></div>')
    h.append('</div></body></html>')
    return "".join(h)
