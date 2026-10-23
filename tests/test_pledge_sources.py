
"""Multi-source pledge. Run: python tests/test_pledge_sources.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mb.pledge_sources import resolve_pledge, from_local_cache, seed_cache_from_csv, CACHE_JSON
from mb.utils import save_json


class DummyClient:
    def get(self, path, params):
        return None  # simulate NSE block


def test_cache_fallback():
    save_json(CACHE_JSON, {"TESTCO": {"pledge": 3.5, "as_of": "2026-03-31", "source": "manual"}})
    r = from_local_cache("TESTCO")
    assert r["ok"] and r["pledge"] == 3.5
    full = resolve_pledge(DummyClient(), "TESTCO.NS", {})
    assert full["pledge"] == 3.5
    assert full["pledge_source"] == "local_cache"
    assert full["pledge_confidence"] == "single"
    print("test_cache_fallback: OK")


if __name__ == "__main__":
    test_cache_fallback()
    print("test_pledge_sources: OK")
