from __future__ import annotations

import math
from typing import Optional


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def parse_float(raw: object, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(raw)
    except Exception:
        return default


def is_finite(value: Optional[float]) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except Exception:
        return False


def safe_ascii(value: object) -> str:
    try:
        text = str(value)
    except Exception:
        text = repr(value)
    return text.encode("ascii", "backslashreplace").decode("ascii")


def fmt_num(value: Optional[float], ndigits: int = 4) -> str:
    if not is_finite(value):
        return "NA"
    return f"{float(value):.{ndigits}f}"
