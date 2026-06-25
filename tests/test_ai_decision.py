from trade_ai.core.strategy import Prediction
from trade_ai.services.ai_decision import choose_signal, score_prediction


def _prediction(**overrides):
    values = {
        "ticker": "AAPL",
        "signal": "BUY",
        "p": 0.62,
        "threshold": 0.42,
        "side": "BUY",
        "reason": "ok",
        "features": {"trend_align": 1, "breakout": 1, "volume_spike": 1, "rsi": 58},
        "h1": "UP",
        "d1": "UP",
    }
    values.update(overrides)
    return Prediction(**values)


def test_ai_decision_approves_strong_candidate():
    decision = choose_signal([_prediction(signal="STRONG_BUY", p=0.72)], lambda ticker: (7, 10))

    assert decision.approved
    assert decision.prediction is not None
    assert decision.prediction.ticker == "AAPL"
    assert decision.reason == "ai_approved"


def test_ai_decision_skips_tight_margin():
    decision = choose_signal([_prediction(p=0.44, threshold=0.42)], lambda ticker: (7, 10))

    assert not decision.approved
    assert decision.reason == "ai_low_margin"


def test_score_uses_ticker_history():
    weak_history = score_prediction(_prediction(), lambda ticker: (2, 10))
    strong_history = score_prediction(_prediction(), lambda ticker: (8, 10))

    assert strong_history > weak_history
