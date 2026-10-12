"""Shared helpers: numerics, JSON I/O, scoring primitives."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np


def num(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ramp(v: Optional[float], lo: float, hi: float) -> Optional[float]:
    """Map v from [lo, hi] → [0, 100]. None-safe."""
    if v is None:
        return None
    return clamp((v - lo) / (hi - lo)) * 100.0


def ramp_inv(v: Optional[float], lo: float, hi: float) -> Optional[float]:
    r = ramp(v, lo, hi)
    return None if r is None else 100.0 - r


def avg(xs: Iterable[Optional[float]]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def clean(o: Any) -> Any:
    """Make anything JSON-safe (numpy types, NaN → None)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 4)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def load_json(path: Path | str, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def save_json(path: Path | str, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean(obj), indent=1))
    tmp.replace(path)  # atomic rename


def fmt(v: Any, decimals: int = 0, suffix: str = "") -> str:
    n = num(v)
    if n is None:
        return "n/a"
    return f"{n:.{decimals}f}{suffix}"
