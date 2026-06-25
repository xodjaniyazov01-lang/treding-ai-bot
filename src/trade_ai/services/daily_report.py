from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from html import escape
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from trade_ai.config import settings
from trade_ai.services.auto_retrain import retrain_progress
from trade_ai.services.backtest import summarize_backtest
from trade_ai.services.db import get_meta, set_meta
from trade_ai.services.telegram import send_message


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _find_column(df: pd.DataFrame, names: tuple[str, ...]) -> Optional[str]:
    lowered = {str(column).lower(): column for column in df.columns}
    for name in names:
        if name.lower() in lowered:
            return str(lowered[name.lower()])
    return None


def _normalize_feedback(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    timestamp_col = _find_column(df, ("timestamp", "ts", "time", "created_at"))
    label_col = _find_column(df, ("label", "feedback", "result", "outcome"))
    if timestamp_col is None or label_col is None:
        return pd.DataFrame()

    out = df.copy()
    out["_timestamp"] = pd.to_datetime(out[timestamp_col], errors="coerce")
    out["_label"] = pd.to_numeric(out[label_col], errors="coerce")
    out = out.dropna(subset=["_timestamp", "_label"]).copy()
    out["_label"] = out["_label"].astype(int)

    symbol_col = _find_column(out, ("symbol", "ticker"))
    signal_col = _find_column(out, ("signal", "side"))
    confidence_col = _find_column(out, ("confidence", "p", "probability"))
    timeframe_col = _find_column(out, ("timeframe", "tf", "tf_label"))
    out["_symbol"] = out[symbol_col].astype(str).str.upper() if symbol_col else ""
    out["_signal"] = out[signal_col].astype(str).str.upper() if signal_col else ""
    out["_confidence"] = pd.to_numeric(out[confidence_col], errors="coerce") if confidence_col else pd.NA
    out["_timeframe"] = out[timeframe_col].astype(str).str.upper() if timeframe_col else ""
    return out


def _normalize_signals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    timestamp_col = _find_column(df, ("timestamp", "ts", "time", "created_at"))
    if timestamp_col is None:
        return pd.DataFrame()
    out = df.copy()
    out["_timestamp"] = pd.to_datetime(out[timestamp_col], errors="coerce")
    return out.dropna(subset=["_timestamp"]).copy()


def _periods(now: datetime) -> tuple[datetime, datetime]:
    day_start = datetime.combine(now.date(), time.min)
    week_start = day_start - timedelta(days=now.weekday())
    return day_start, week_start


def _count_rows_since(df: pd.DataFrame, start: datetime) -> int:
    if df.empty or "_timestamp" not in df.columns:
        return 0
    return int((df["_timestamp"] >= start).sum())


def _top_value(df: pd.DataFrame, label: int, column: str) -> str:
    if df.empty or column not in df.columns:
        return "N/A"
    rows = df[df["_label"] == label]
    if rows.empty:
        return "N/A"
    counts = rows[column].replace("", pd.NA).dropna().value_counts()
    if counts.empty:
        return "N/A"
    return f"{counts.index[0]} ({int(counts.iloc[0])})"


def _active_timeframe(df: pd.DataFrame) -> str:
    if df.empty or "_timeframe" not in df.columns:
        return "N/A"
    counts = df["_timeframe"].replace("", pd.NA).dropna().value_counts()
    if counts.empty:
        return "N/A"
    return f"{counts.index[0]} ({int(counts.iloc[0])})"


def _load_backtest_results() -> dict:
    if not settings.BACKTEST_RESULTS_PATH.exists():
        return summarize_backtest()
    try:
        data = json.loads(settings.BACKTEST_RESULTS_PATH.read_text(encoding="utf-8", errors="ignore"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return summarize_backtest()


def build_daily_report(now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    day_start, week_start = _periods(now)
    feedback = _normalize_feedback(_read_csv(settings.FEEDBACK_LOG_PATH))
    signals = _normalize_signals(_read_csv(settings.SIGNALS_CSV_PATH))
    backtest = _load_backtest_results()

    today_feedback = feedback[feedback["_timestamp"] >= day_start] if not feedback.empty else pd.DataFrame()
    week_feedback = feedback[feedback["_timestamp"] >= week_start] if not feedback.empty else pd.DataFrame()
    today_signals = _count_rows_since(signals, day_start) or len(today_feedback)
    week_signals = _count_rows_since(signals, week_start) or len(week_feedback)
    progress = retrain_progress()
    progress_line = (
        f"Feedback progress: <code>{progress['delta']}/{progress['step']}</code> "
        f"(<code>{progress['remaining']}</code> qoldi)"
    )

    if today_feedback.empty:
        return (
            "<b>Kunlik signal hisoboti</b>\n\n"
            f"Sana: <code>{escape(now.date().isoformat())}</code>\n"
            "Bugun feedback yo'q.\n\n"
            f"Haftalik feedback: <code>{len(week_feedback)}</code>\n"
            f"Haftalik signal: <code>{week_signals}</code>\n"
            f"{progress_line}\n"
            f"Backtest win rate: <code>{float(backtest.get('win_rate', 0.0)) * 100:.1f}%</code>"
        )

    wins = int((today_feedback["_label"] == 1).sum())
    losses = int((today_feedback["_label"] == 0).sum())
    total_feedback = wins + losses
    win_rate = round((wins / total_feedback) * 100, 1) if total_feedback else 0.0
    confidence = pd.to_numeric(today_feedback["_confidence"], errors="coerce").dropna()
    avg_confidence = float(confidence.mean()) if not confidence.empty else 0.0

    return "\n".join(
        [
            "<b>Kunlik signal hisoboti</b>",
            "",
            f"Sana: <code>{escape(now.date().isoformat())}</code>",
            f"Jami signal: <code>{today_signals}</code> bugun / <code>{week_signals}</code> hafta",
            f"WIN / LOSS: <code>{wins}</code> / <code>{losses}</code>",
            f"Win rate: <code>{win_rate:.1f}%</code>",
            f"Eng yaxshi ticker: <code>{escape(_top_value(today_feedback, 1, '_symbol'))}</code>",
            f"Eng yomon ticker: <code>{escape(_top_value(today_feedback, 0, '_symbol'))}</code>",
            f"Avg confidence: <code>{avg_confidence:.2f}</code>",
            f"Eng faol timeframe: <code>{escape(_active_timeframe(today_feedback))}</code>",
            progress_line,
            f"Backtest win rate: <code>{float(backtest.get('win_rate', 0.0)) * 100:.1f}%</code>",
        ]
    )


def _report_due(now: datetime, report_time: str) -> bool:
    try:
        hour_raw, minute_raw = report_time.split(":", 1)
        scheduled = time(hour=int(hour_raw), minute=int(minute_raw))
    except Exception:
        scheduled = time(hour=20, minute=0)
    return now.time() >= scheduled


def maybe_send_daily_report(
    now: Optional[datetime] = None,
    sender: Callable[[str], object] = send_message,
) -> bool:
    now = now or datetime.now()
    if not _report_due(now, settings.DAILY_REPORT_TIME):
        return False
    sent_key = f"daily_report_sent:{now.date().isoformat()}"
    if get_meta(sent_key, "") == "1":
        return False
    sender(build_daily_report(now))
    set_meta(sent_key, "1")
    return True
