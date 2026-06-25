from __future__ import annotations

import json
import logging
from typing import Callable, Iterable

import requests

from trade_ai.config import settings
from trade_ai.core.strategy import Prediction
from trade_ai.services.ai_decision import AIDecision, choose_signal, rank_predictions

logger = logging.getLogger("trade_ai.claude_decision")

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ALLOWED_ACTIONS = {"approve", "skip", "reduce_risk"}


def _compact_prediction(
    prediction: Prediction,
    score: float,
    win_rate_lookup: Callable[[str], tuple[int, int]],
) -> dict:
    wins, total = 0, 0
    try:
        wins, total = win_rate_lookup(prediction.ticker)
    except Exception:
        pass
    return {
        "ticker": prediction.ticker,
        "signal": prediction.signal,
        "side": prediction.side,
        "probability": round(float(prediction.p), 4),
        "threshold": round(float(prediction.threshold), 4),
        "margin": round(float(prediction.p) - float(prediction.threshold), 4),
        "local_ai_score": round(float(score), 4),
        "reason": prediction.reason,
        "h1_trend": prediction.h1,
        "d1_trend": prediction.d1,
        "squeeze": bool(prediction.squeeze),
        "breakout": prediction.breakout,
        "entry": prediction.entry,
        "atr": prediction.atr,
        "sl": prediction.sl,
        "tp": prediction.tp,
        "ticker_recent_winrate": {
            "wins": int(wins),
            "total": int(total),
            "rate": round(wins / max(1, total), 4) if total else None,
        },
        "features": prediction.features or {},
    }


def _parse_json_object(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _call_claude(payload: dict) -> dict:
    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": settings.CLAUDE_MODEL,
        "max_tokens": settings.CLAUDE_MAX_TOKENS,
        "temperature": 0,
        "system": (
            "You are a strict trading signal selector and risk gate. Return only JSON. "
            "Do not explain. Valid action values: approve, skip, reduce_risk. "
            "Choose only a ticker from candidates. Use skip for weak margin, trend conflict, "
            "bad volatility, overextended RSI, poor recent ticker history, or unclear setup."
        ),
        "messages": [
            {
                "role": "user",
                "content": (
                    "Select the single best signal candidate or skip all. "
                    "Return JSON exactly like "
                    "{\"action\":\"approve\",\"ticker\":\"AAPL\",\"confidence\":0.0,\"reason\":\"short_code\"}.\n"
                    f"{json.dumps(payload, ensure_ascii=True, sort_keys=True)}"
                ),
            }
        ],
    }
    response = requests.post(
        ANTHROPIC_MESSAGES_URL,
        headers=headers,
        json=body,
        timeout=settings.CLAUDE_TIMEOUT_SEC,
    )
    response.raise_for_status()
    data = response.json()
    text_parts = []
    for item in data.get("content", []):
        if item.get("type") == "text":
            text_parts.append(str(item.get("text") or ""))
    return _parse_json_object("\n".join(text_parts))


def choose_signal_with_claude(
    predictions: Iterable[Prediction],
    win_rate_lookup: Callable[[str], tuple[int, int]],
) -> AIDecision:
    prediction_list = list(predictions)
    local = choose_signal(prediction_list, win_rate_lookup)
    if not settings.CLAUDE_DECISION_ENABLED:
        return local
    if not settings.ANTHROPIC_API_KEY:
        return local if local.prediction is None else AIDecision(local.prediction, local.approved, local.score, "claude_missing_key_local_fallback")
    if (not settings.CLAUDE_FULL_CONTROL_ENABLED) and (not local.approved or local.prediction is None):
        return local

    ranked = rank_predictions(prediction_list, win_rate_lookup)
    if not ranked:
        return local
    top_n = max(1, min(12, int(settings.CLAUDE_TOP_N)))
    shortlisted = ranked[:top_n]
    candidates_by_ticker = {prediction.ticker.upper(): (score, prediction) for score, prediction in shortlisted}
    payload = {
        "selection_policy": {
            "min_local_score": settings.AI_MIN_DECISION_SCORE,
            "min_probability_margin": settings.AI_MIN_PROBA_MARGIN,
            "min_claude_confidence": settings.CLAUDE_MIN_CONFIDENCE,
            "claude_full_control": bool(settings.CLAUDE_FULL_CONTROL_ENABLED),
            "prefer": [
                "higher probability margin",
                "multi-timeframe trend alignment",
                "breakout with volume confirmation",
                "good recent ticker winrate",
                "clean RSI not overextended",
            ],
            "veto": [
                "probability is only barely above threshold",
                "trend context is mixed or missing",
                "RSI is extreme against the trade",
                "ATR/volatility context is unclear",
            ],
        },
        "candidates": [
            _compact_prediction(prediction, score, win_rate_lookup)
            for score, prediction in shortlisted
        ],
    }
    try:
        result = _call_claude(payload)
    except Exception as exc:
        logger.warning("Claude decision failed, using local AI fallback: %s", exc)
        return local if local.prediction is None else AIDecision(local.prediction, local.approved, local.score, "claude_error_local_fallback")

    action = str(result.get("action") or "").strip().lower()
    if action not in ALLOWED_ACTIONS:
        logger.warning("Claude decision invalid action=%s, using local AI fallback", action)
        return local if local.prediction is None else AIDecision(local.prediction, local.approved, local.score, "claude_invalid_local_fallback")
    fallback_ticker = local.prediction.ticker if local.prediction is not None else shortlisted[0][1].ticker
    selected_ticker = str(result.get("ticker") or fallback_ticker).strip().upper()
    if selected_ticker not in candidates_by_ticker:
        logger.warning("Claude decision invalid ticker=%s, using local AI fallback", selected_ticker)
        return local if local.prediction is None else AIDecision(local.prediction, local.approved, local.score, "claude_invalid_ticker_local_fallback")
    selected_score, selected_prediction = candidates_by_ticker[selected_ticker]
    try:
        claude_confidence = float(result.get("confidence", selected_score))
    except Exception:
        claude_confidence = selected_score
    score = max(0.0, min(1.0, claude_confidence))
    reason = str(result.get("reason") or action).strip().lower().replace(" ", "_")[:80]

    if action == "skip":
        return AIDecision(selected_prediction, False, score, f"claude_skip:{reason}")
    if score < settings.CLAUDE_MIN_CONFIDENCE:
        return AIDecision(selected_prediction, False, score, "claude_low_confidence")
    if action == "reduce_risk":
        return AIDecision(selected_prediction, True, score, f"claude_reduce_risk:{reason}")
    return AIDecision(selected_prediction, True, score, f"claude_approve:{reason}")
