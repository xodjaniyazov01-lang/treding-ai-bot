from __future__ import annotations

import csv
import json
from datetime import datetime
from typing import Optional

from trade_ai.config import settings

FEEDBACK_COLUMNS = [
    "timestamp",
    "symbol",
    "signal",
    "confidence",
    "timeframe",
    *settings.PATTERN_FEATURES,
    "label",
]


def _load_pending() -> dict:
    if not settings.FEEDBACK_PENDING_PATH.exists():
        return {}
    try:
        raw = settings.FEEDBACK_PENDING_PATH.read_text(encoding="utf-8", errors="ignore")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_pending(data: dict) -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.FEEDBACK_PENDING_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_pending_feedback(
    signal_id: str,
    timestamp: datetime,
    symbol: str,
    signal: str,
    confidence: float,
    timeframe: str,
    features: Optional[dict],
) -> None:
    if not signal_id or not features:
        return
    row = {
        "timestamp": timestamp.isoformat(timespec="seconds"),
        "symbol": (symbol or "").upper(),
        "signal": signal,
        "confidence": float(confidence),
        "timeframe": timeframe,
    }
    for column in settings.PATTERN_FEATURES:
        row[column] = features.get(column)
    pending = _load_pending()
    pending[signal_id] = row
    _save_pending(pending)


def append_feedback(signal_id: str, label: int) -> bool:
    pending = _load_pending()
    row = pending.get(signal_id)
    if not isinstance(row, dict):
        return False
    row = dict(row)
    row["label"] = int(label)
    settings.FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    exists = settings.FEEDBACK_LOG_PATH.exists() and settings.FEEDBACK_LOG_PATH.stat().st_size > 0
    with settings.FEEDBACK_LOG_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FEEDBACK_COLUMNS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in FEEDBACK_COLUMNS})
    pending.pop(signal_id, None)
    _save_pending(pending)
    return True
