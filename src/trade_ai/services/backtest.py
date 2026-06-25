from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable

import pandas as pd

from trade_ai.config import settings

SIGNAL_FEATURE_COLUMNS = [column for column in settings.PATTERN_FEATURES if column != "side"]
SIGNAL_COLUMNS = [
    "signal_id",
    "timestamp",
    "symbol",
    "signal",
    "side",
    "timeframe",
    "interval",
    "confidence",
    "threshold",
    "entry",
    "sl",
    "tp",
    "status",
    "outcome",
    "close_timestamp",
    "close_price",
    "price_at_signal",
    "price_at_check",
    "pnl_pct",
    "validation_outcome",
    "validated_at",
    "reason",
    "model_version",
    *SIGNAL_FEATURE_COLUMNS,
]


def _ts_to_iso(value) -> str:
    try:
        if value is None or value == "":
            return ""
        return datetime.fromtimestamp(int(value)).isoformat(timespec="seconds")
    except Exception:
        return str(value or "")


def _canonical_outcome(value: object) -> str:
    outcome = str(value or "").upper()
    if outcome in {"WIN", "TAKE_PROFIT"}:
        return "TP"
    if outcome in {"LOSS", "STOP_LOSS"}:
        return "SL"
    return outcome


def _read_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    if not path.exists():
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except Exception:
            continue
    return pd.DataFrame(rows)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)


def _db_rows() -> list[dict]:
    if not settings.SIGNALS_DB_PATH.exists():
        return []
    con = sqlite3.connect(str(settings.SIGNALS_DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM signals ORDER BY ts ASC;").fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        con.close()


def _row_from_db(row: dict) -> dict:
    side = str(row.get("side") or "").upper()
    outcome = _canonical_outcome(row.get("outcome"))
    status = str(row.get("status") or "").upper()
    validation_outcome = str(row.get("validation_outcome") or "").upper()
    return {
        "signal_id": row.get("id", ""),
        "timestamp": _ts_to_iso(row.get("ts")),
        "symbol": str(row.get("ticker") or "").upper(),
        "signal": side,
        "side": side,
        "timeframe": str(row.get("tf_label") or "").upper(),
        "interval": row.get("interval", ""),
        "confidence": row.get("p", ""),
        "threshold": "",
        "entry": row.get("entry", ""),
        "sl": row.get("sl", ""),
        "tp": row.get("tp", ""),
        "status": status,
        "outcome": outcome,
        "close_timestamp": _ts_to_iso(row.get("close_ts")),
        "close_price": row.get("close_price", ""),
        "price_at_signal": row.get("price_at_signal", ""),
        "price_at_check": row.get("price_at_check", ""),
        "pnl_pct": row.get("pnl_pct", ""),
        "validation_outcome": validation_outcome,
        "validated_at": row.get("validated_at", ""),
        "reason": "",
        "model_version": settings.MODEL_VERSION,
        **{column: "" for column in SIGNAL_FEATURE_COLUMNS},
    }


def _normalize_rows(rows: Iterable[dict]) -> pd.DataFrame:
    out = pd.DataFrame(list(rows))
    if out.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    for column in SIGNAL_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    return out[SIGNAL_COLUMNS].copy()


def load_signals() -> pd.DataFrame:
    if not settings.SIGNALS_CSV_PATH.exists() and not settings.SIGNALS_LOG_PATH.exists():
        return export_signals_from_db()
    frames = []
    csv_df = _read_csv(settings.SIGNALS_CSV_PATH)
    log_df = _read_jsonl(settings.SIGNALS_LOG_PATH)
    if not csv_df.empty:
        frames.append(csv_df)
    if not log_df.empty:
        frames.append(log_df)
    if not frames:
        return export_signals_from_db()
    df = pd.concat(frames, ignore_index=True, sort=False)
    if "signal_id" in df.columns:
        df = df.drop_duplicates(subset=["signal_id"], keep="last")
    return _normalize_rows(df.to_dict(orient="records"))


def export_signals_from_db() -> pd.DataFrame:
    df = _normalize_rows(_row_from_db(row) for row in _db_rows())
    try:
        settings.SIGNALS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(settings.SIGNALS_CSV_PATH, index=False, encoding="utf-8")
        with settings.SIGNALS_LOG_PATH.open("w", encoding="utf-8") as handle:
            for row in df.to_dict(orient="records"):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return df


def _outcome_series(df: pd.DataFrame) -> pd.Series:
    if "outcome" not in df.columns:
        return pd.Series(dtype=str)
    out = df["outcome"].fillna("").astype(str).map(_canonical_outcome)
    fallback = df.get("status", pd.Series([""] * len(df))).fillna("").astype(str).str.upper()
    return out.mask(out.isin({"", "UNKNOWN", "PENDING"}), fallback)


def _group_metrics(df: pd.DataFrame, column: str) -> dict:
    if df.empty or column not in df.columns:
        return {}
    rows = []
    for key, group in df.groupby(df[column].fillna("").astype(str).replace("", "N/A")):
        outcomes = _outcome_series(group)
        win = int((outcomes == "TP").sum())
        loss = int((outcomes == "SL").sum())
        denom = win + loss
        rows.append((str(key), {"total": int(len(group)), "win": win, "loss": loss, "win_rate": round(win / denom, 4) if denom else 0.0}))
    return {key: value for key, value in sorted(rows)}


def _top_by_outcome(df: pd.DataFrame, outcome: str) -> str:
    if df.empty or "symbol" not in df.columns:
        return ""
    rows = df[_outcome_series(df) == outcome]
    if rows.empty:
        return ""
    counts = rows["symbol"].fillna("").astype(str).str.upper().replace("", pd.NA).dropna().value_counts()
    return str(counts.index[0]) if not counts.empty else ""


def summarize_backtest(df: pd.DataFrame | None = None) -> dict:
    df = load_signals() if df is None else _normalize_rows(df.to_dict(orient="records"))
    outcomes = _outcome_series(df)
    win = int((outcomes == "TP").sum())
    loss = int((outcomes == "SL").sum())
    ambiguous = int((outcomes == "AMBIGUOUS").sum())
    open_count = int(outcomes.isin({"OPEN", "PENDING", "UNKNOWN", ""}).sum())
    denom = win + loss

    pnl = pd.to_numeric(df.get("pnl_pct", pd.Series(dtype=float)), errors="coerce")
    confidence = pd.to_numeric(df.get("confidence", pd.Series(dtype=float)), errors="coerce")
    summary = {
        "total_signals": int(len(df)),
        "win": win,
        "loss": loss,
        "ambiguous": ambiguous,
        "open": open_count,
        "win_rate": round(win / denom, 4) if denom else 0.0,
        "avg_pnl_pct": round(float(pnl.dropna().mean()), 4) if not pnl.dropna().empty else 0.0,
        "avg_confidence_win": round(float(confidence[outcomes == "TP"].dropna().mean()), 4) if not confidence[outcomes == "TP"].dropna().empty else 0.0,
        "avg_confidence_loss": round(float(confidence[outcomes == "SL"].dropna().mean()), 4) if not confidence[outcomes == "SL"].dropna().empty else 0.0,
        "best_ticker": _top_by_outcome(df, "TP"),
        "worst_ticker": _top_by_outcome(df, "SL"),
        "by_timeframe": _group_metrics(df, "timeframe"),
        "by_pattern": _group_metrics(df, "pattern_name"),
        "model_version": settings.MODEL_VERSION,
    }
    try:
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        settings.BACKTEST_RESULTS_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return summary


def load_backtest_results() -> dict:
    if not settings.BACKTEST_RESULTS_PATH.exists():
        return {}
    try:
        data = json.loads(settings.BACKTEST_RESULTS_PATH.read_text(encoding="utf-8", errors="ignore"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_backtest_report() -> str:
    data = load_backtest_results()
    if not data:
        return "Backtest ma'lumoti hali yo'q"

    total = int(data.get("total_signals", 0) or 0)
    win = int(data.get("win", 0) or 0)
    loss = int(data.get("loss", 0) or 0)
    win_rate = float(data.get("win_rate", 0.0) or 0.0) * 100
    avg_pnl = float(data.get("avg_pnl_pct", 0.0) or 0.0)
    pnl_sign = "+" if avg_pnl > 0 else ""
    lines = [
        "<b>Backtest hisoboti</b>",
        "",
        f"WIN: <code>{win}</code> | LOSS: <code>{loss}</code>",
        f"Win rate: <code>{win_rate:.1f}%</code>",
        f"Avg PnL: <code>{pnl_sign}{avg_pnl:.2f}%</code>",
        f"Jami signal: <code>{total}</code>",
        "",
        f"Best: <code>{escape(str(data.get('best_ticker') or 'N/A'))}</code>",
        f"Worst: <code>{escape(str(data.get('worst_ticker') or 'N/A'))}</code>",
    ]
    by_timeframe = data.get("by_timeframe")
    if isinstance(by_timeframe, dict) and by_timeframe:
        lines.extend(["", "<b>Timeframe breakdown</b>"])
        for timeframe, metrics in sorted(by_timeframe.items()):
            if not isinstance(metrics, dict):
                continue
            tf_win_rate = float(metrics.get("win_rate", 0.0) or 0.0) * 100
            lines.append(f"{escape(str(timeframe))}: <code>{tf_win_rate:.1f}% win</code>")
    return "\n".join(lines)


def export_and_summarize() -> dict:
    df = export_signals_from_db()
    return summarize_backtest(df)
