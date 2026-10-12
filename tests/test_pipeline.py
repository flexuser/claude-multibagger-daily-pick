"""End-to-end demo-mode checks. Run: python tests/test_pipeline.py"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mb import pipeline
from mb.config import CFG


def run():
    return pipeline.run(demo=True, no_notify=True)


def main():
    for d in ("data", "docs"):
        (ROOT / d).mkdir(exist_ok=True)

    orig = pipeline.demo_diligence
    try:
        r = run()
        assert r["pick"] is not None, "demo should produce a pick"
        top = r["pick"]["ticker"]
        runner = r["bench"][0] if r["bench"] else None

        # Red-gate on top → should pick next
        pipeline.demo_diligence = lambda c: dict(orig(c), verdict="red") if c["ticker"] == top else orig(c)
        r = run()
        assert r["pick"] is None or r["pick"]["ticker"] != top
        assert any(x["ticker"] == top for x in r.get("dd_rejected", []))

        # All red → no pick
        pipeline.demo_diligence = lambda c: dict(orig(c), verdict="red")
        r = run()
        assert r["pick"] is None and r["dd_blocked"]

        pipeline.demo_diligence = orig
        r = run()
        assert r["pick"] is not None
        print(f"test_pipeline: OK (pick={r['pick']['ticker']} score={r['pick']['score']})")
    finally:
        pipeline.demo_diligence = orig


if __name__ == "__main__":
    main()
