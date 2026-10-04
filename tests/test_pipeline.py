"""End-to-end demo-mode checks: DD gate, all-red, pick stability, track record. Run: python tests/test_pipeline.py"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scan  # noqa: E402


def run(*extra):
    sys.argv = ["scan.py", "--demo", "--no-notify", *extra]
    scan.main()
    return json.loads((ROOT / "docs" / "latest.json").read_text())


def main():
    for d in ("data", "docs"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    orig = scan.demo_diligence
    try:
        r = run()
        top, runner = r["pick"]["ticker"], r["bench"][0]
        scan.demo_diligence = lambda c: dict(orig(c), verdict="red") if c["ticker"] == top else orig(c)
        r = run()
        assert r["pick"]["ticker"] != top and r["dd_rejected"][0]["ticker"] == top
        scan.demo_diligence = lambda c: dict(orig(c), verdict="red")
        r = run()
        assert r["pick"] is None and r["dd_blocked"]
        scan.demo_diligence = orig
        r = run()
        if r["pick"]["score"] - runner["score"] < scan.CFG["hysteresis"]:
            (ROOT / "data" / "picks.json").write_text(json.dumps(
                [dict(date="2026-10-01", ticker=runner["ticker"], name="x", price=100, score=70, nifty=22000)]))
            assert run()["pick"]["ticker"] == runner["ticker"]
        eps, summ = scan.track_episodes(
            [dict(date="d1", ticker="A", name="A", price=100, score=70, nifty=100),
             dict(date="d2", ticker="A", name="A", price=105, score=71, nifty=101),
             dict(date="d3", ticker="B", name="B", price=50, score=72, nifty=102)],
            {"A": {"price": 120}, "B": {"price": 45}}, dict(last=110))
        assert summ["episodes"] == 2 and eps[1]["days"] == 2
        print("pipeline tests ok")
    finally:
        scan.demo_diligence = orig
        for d in ("data", "docs"):
            shutil.rmtree(ROOT / d, ignore_errors=True)
            (ROOT / d).mkdir()
            (ROOT / d / ".gitkeep").touch()


if __name__ == "__main__":
    main()
