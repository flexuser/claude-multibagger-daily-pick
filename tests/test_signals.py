import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mb.signals import classify_announcement

def test_esop_not_approval():
    cats = classify_announcement("In-principle approval", "ESOP listing of equity shares under employee stock option scheme")
    assert "approval" not in cats

def test_sast_not_acquisition():
    cats = classify_announcement("Disclosure under Regulation 29", "Substantial acquisition of shares SAST by investor")
    assert "acquisition" not in cats

if __name__ == "__main__":
    test_esop_not_approval()
    test_sast_not_acquisition()
    print("test_signals: OK")
