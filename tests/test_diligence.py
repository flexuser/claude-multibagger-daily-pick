"""Run: python tests/test_diligence.py  (no network, no keys needed)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diligence as D
import notify

CTX = dict(ticker="TEST.NS", name="Test Co", sector="Industrials", mcap_cr=2000, facts="x", flags="", events="")
GOOD = ('Here you go:\n```json\n{"verdict":"green","summary":"Makes parts.","management":"ok","controversies":"not found",'
        '"business_update":"up","order_book":"Rs 400 cr","strengths":["a"],"risks":["b"],"sources":["https://example.com/a","javascript:alert(1)"]}\n```')


def test_extract_and_normalize():
    r = D.normalize(D.extract_json(GOOD))
    assert r["verdict"] == "green" and r["sources"] == ["https://example.com/a"]
    assert D.extract_json("no json here") is None


def test_green_without_sources_downgraded():
    r = D.normalize({"verdict": "green", "summary": "s", "sources": []})
    assert r["verdict"] == "yellow" and any("no sources" in x.lower() for x in r["risks"])


def test_bad_verdict_and_missing_summary():
    assert D.normalize({"verdict": "bullish", "summary": "s"})["verdict"] == "yellow"
    assert D.normalize({"verdict": "green"}) is None


def test_gemini_flow_and_cache(monkeypatch_calls=[]):
    calls = []
    def fake_gemini(prompt, key, model, grounded=True):
        calls.append(model)
        return GOOD, ["https://grounding.example/x"]
    D.call_gemini = fake_gemini
    env = {"GEMINI_API_KEY": "SECRETKEY"}
    cache = {}
    res = D.due_diligence(CTX, "2026-10-04", cache, env=env, pause=0)
    assert res["status"] == "ok" and res["provider"] == "gemini" and "https://grounding.example/x" in res["sources"]
    again = D.due_diligence(CTX, "2026-10-06", cache, env=env, pause=0)
    assert again.get("cached") and len(calls) == 1          # served from cache within the TTL
    D.due_diligence(CTX, "2026-10-20", cache, env=env, pause=0)
    assert len(calls) == 2                                   # expired, refetched


def test_fallback_to_anthropic_and_key_scrub():
    def bad(prompt, key, model, grounded=True):
        raise RuntimeError("HTTP 400 for key SECRETKEY")
    def ant(prompt, key, model):
        return GOOD, []
    D.call_gemini, D.call_anthropic = bad, ant
    D.GEMINI_MODELS = ["m1"]
    env = {"GEMINI_API_KEY": "SECRETKEY", "ANTHROPIC_API_KEY": "K2"}
    res = D.due_diligence(CTX, "2026-10-04", {}, env=env, pause=0)
    assert res["status"] == "ok" and res["provider"] == "anthropic"


def test_all_fail_reports_reason_without_key():
    def bad(prompt, key, model, grounded=True):
        raise RuntimeError("HTTP 429 key=SECRETKEY")
    D.call_gemini = bad
    D.web_snippets = lambda name: ""
    res = D.due_diligence(CTX, "2026-10-04", {}, env={"GEMINI_API_KEY": "SECRETKEY"}, pause=0)
    assert res["status"] == "failed" and "SECRETKEY" not in res["reason"]


def test_no_keys():
    res = D.due_diligence(CTX, "2026-10-04", {}, env={}, pause=0)
    assert res["status"] == "unavailable"


def test_notify_message():
    r = dict(generated="2026-10-04", dd_blocked=False, pick=dict(name="Test Co", ticker="TEST.NS", score=81.2, streak=1, price=123.4,
             diligence=dict(verdict="yellow"), flags=[dict(sev="high", text="Pledge 22%")]))
    m = notify.build_message(r, "https://u.github.io/r/")
    assert "81/100" in m and "DD yellow" in m and "Pledge 22%" in m and m.endswith("https://u.github.io/r/")
    assert "no pick" in notify.build_message(dict(generated="d", pick=None, dd_blocked=True), "")
    assert notify.pages_url({"GITHUB_REPOSITORY": "me/proj"}) == "https://me.github.io/proj/"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
