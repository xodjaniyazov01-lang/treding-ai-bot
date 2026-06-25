from __future__ import annotations

import logging
from typing import Callable

import pandas as pd

from trade_ai.config import settings
from trade_ai.core.model import load_training_metrics, train_and_save
from trade_ai.core.strategy import load_prediction_model
from trade_ai.services.telegram import send_message

logger = logging.getLogger("trade_ai.auto_retrain")


def feedback_count() -> int:
    if not settings.FEEDBACK_LOG_PATH.exists():
        return 0
    try:
        df = pd.read_csv(settings.FEEDBACK_LOG_PATH, usecols=["label"])
    except Exception:
        try:
            df = pd.read_csv(settings.FEEDBACK_LOG_PATH)
        except Exception:
            return 0
    return int(len(df))


def retrain_progress() -> dict:
    metrics = load_training_metrics()
    count = feedback_count()
    try:
        last_feedback_count = int(metrics.get("last_feedback_count", 0) or 0)
    except Exception:
        last_feedback_count = 0
    step = max(1, int(settings.AUTO_RETRAIN_FEEDBACK_STEP))
    delta = max(0, count - last_feedback_count)
    return {
        "count": count,
        "last_count": last_feedback_count,
        "delta": delta,
        "step": step,
        "remaining": max(0, step - delta),
    }


def _fmt_f1(value: float | None) -> str:
    return "N/A" if value is None else f"{float(value):.3f}"


def build_retrain_message(previous_f1: float | None, current_f1: float, previous_rows: int | None, current_rows: int, threshold: float) -> str:
    previous_rows_text = "N/A" if previous_rows is None else str(previous_rows)
    return (
        "<b>Model yangilandi</b>\n"
        f"F1: <code>{_fmt_f1(previous_f1)} -> {current_f1:.3f}</code>\n"
        f"Rows: <code>{previous_rows_text} -> {current_rows}</code>\n"
        f"Threshold: <code>{threshold:.2f}</code>"
    )


def maybe_auto_retrain(sender: Callable[[str], object] = send_message) -> bool:
    progress = retrain_progress()
    count = int(progress["count"])
    delta = int(progress["delta"])
    if count <= 0 or delta < settings.AUTO_RETRAIN_FEEDBACK_STEP:
        return False

    try:
        result = train_and_save(feedback_count=count)
    except Exception as exc:
        logger.exception("Auto retrain failed: %r", exc)
        return False

    if result.model_updated:
        load_prediction_model.cache_clear()
        sender(
            build_retrain_message(
                previous_f1=result.previous_best_f1,
                current_f1=result.best_f1,
                previous_rows=result.previous_rows,
                current_rows=result.rows,
                threshold=result.best_threshold,
            )
        )
        logger.info("Auto retrain updated model feedback_count=%d delta=%d f1=%.3f", count, delta, result.best_f1)
    else:
        logger.info(
            "Auto retrain skipped model update: feedback_count=%d delta=%d previous_f1=%s current_f1=%.3f",
            count,
            delta,
            _fmt_f1(result.previous_best_f1),
            result.best_f1,
        )
    return True
