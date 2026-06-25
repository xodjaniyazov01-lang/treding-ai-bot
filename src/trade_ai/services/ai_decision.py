from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from trade_ai.config import settings
from trade_ai.core.strategy import Prediction
from trade_ai.utils.helpers import is_finite


@dataclass(frozen=True)
class AIDecision:
    prediction: Prediction | None
    approved: bool
    score: float
    reason: str


def _is_signal(prediction: Prediction) -> bool:
    signal = (prediction.signal or "").upper()
    return (
        ("BUY" in signal or "SELL" in signal)
        and "HOLD" not in signal
        and "CONFLICT" not in signal
        and prediction.reason not in {"data_error", "model_error"}
        and is_finite(prediction.p)
    )


def _feature_bias(prediction: Prediction) -> float:
    features = prediction.features or {}
    bias = 0.0
    if int(features.get("trend_align") or 0):
        bias += 0.02
    if int(features.get("breakout") or 0):
        bias += 0.02
    if int(features.get("volume_spike") or 0):
        bias += 0.02
    if prediction.squeeze and prediction.breakout in ("UP", "DOWN"):
        bias += 0.04

    signal = (prediction.signal or "").upper()
    try:
        rsi = float(features.get("rsi"))
    except Exception:
        rsi = 50.0
    if "BUY" in signal:
        if rsi >= 78:
            bias -= 0.04
        elif rsi < 45:
            bias -= 0.03
    elif "SELL" in signal:
        if rsi <= 22:
            bias -= 0.04
        elif rsi > 55:
            bias -= 0.03
    return bias


def _trend_bias(prediction: Prediction) -> float:
    signal = (prediction.signal or "").upper()
    h1 = (prediction.h1 or "").upper()
    d1 = (prediction.d1 or "").upper()
    if "BUY" in signal and h1 == "UP" and d1 == "UP":
        return 0.05
    if "SELL" in signal and h1 == "DOWN" and d1 == "DOWN":
        return 0.05
    if h1 == "NA" or d1 == "NA":
        return 0.0
    if h1 and d1 and h1 != d1:
        return -0.03
    return 0.0


def _history_bias(prediction: Prediction, win_rate_lookup: Callable[[str], tuple[int, int]]) -> float:
    try:
        wins, total = win_rate_lookup(prediction.ticker)
    except Exception:
        return 0.0
    if total < 3:
        return 0.0
    win_rate = wins / max(1, total)
    return (win_rate - 0.50) * 0.16


def score_prediction(prediction: Prediction, win_rate_lookup: Callable[[str], tuple[int, int]]) -> float:
    score = float(prediction.p)
    margin = float(prediction.p) - float(prediction.threshold)
    score += max(-0.08, min(0.12, margin * 0.35))

    signal = (prediction.signal or "").upper()
    if "STRONG" in signal:
        score += 0.06
    if "EXPLOSIVE" in signal:
        score += 0.08
    if prediction.reason == "squeeze_breakout":
        score += 0.04

    score += _trend_bias(prediction)
    score += _feature_bias(prediction)
    score += _history_bias(prediction, win_rate_lookup)
    return max(0.0, min(1.0, score))


def rank_predictions(
    predictions: Iterable[Prediction],
    win_rate_lookup: Callable[[str], tuple[int, int]],
) -> list[tuple[float, Prediction]]:
    candidates = [prediction for prediction in predictions if _is_signal(prediction)]
    return sorted(
        ((score_prediction(prediction, win_rate_lookup), prediction) for prediction in candidates),
        key=lambda item: item[0],
        reverse=True,
    )


def choose_signal(
    predictions: Iterable[Prediction],
    win_rate_lookup: Callable[[str], tuple[int, int]],
) -> AIDecision:
    ranked = rank_predictions(predictions, win_rate_lookup)
    if not ranked:
        return AIDecision(None, False, 0.0, "no_signal")

    score, prediction = ranked[0]
    margin = float(prediction.p) - float(prediction.threshold)
    if margin < settings.AI_MIN_PROBA_MARGIN:
        return AIDecision(prediction, False, score, "ai_low_margin")
    if score < settings.AI_MIN_DECISION_SCORE:
        return AIDecision(prediction, False, score, "ai_low_score")
    return AIDecision(prediction, True, score, "ai_approved")
