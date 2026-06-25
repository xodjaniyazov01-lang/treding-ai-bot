from trade_ai.core.strategy import Prediction
from trade_ai.services.claude_decision import choose_signal_with_claude


def _prediction(**overrides):
    values = {
        "ticker": "AAPL",
        "signal": "STRONG_BUY",
        "p": 0.72,
        "threshold": 0.42,
        "side": "BUY",
        "reason": "ok",
        "features": {"trend_align": 1, "breakout": 1, "volume_spike": 1, "rsi": 58},
        "h1": "UP",
        "d1": "UP",
    }
    values.update(overrides)
    return Prediction(**values)


def test_claude_disabled_uses_local_ai(monkeypatch):
    monkeypatch.setattr("trade_ai.config.settings.CLAUDE_DECISION_ENABLED", False)

    decision = choose_signal_with_claude([_prediction()], lambda ticker: (7, 10))

    assert decision.approved
    assert decision.reason == "ai_approved"


def test_claude_skip_blocks_signal(monkeypatch):
    monkeypatch.setattr("trade_ai.config.settings.CLAUDE_DECISION_ENABLED", True)
    monkeypatch.setattr("trade_ai.config.settings.ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "trade_ai.services.claude_decision._call_claude",
        lambda payload: {"action": "skip", "confidence": 0.81, "reason": "weak_setup"},
    )

    decision = choose_signal_with_claude([_prediction()], lambda ticker: (7, 10))

    assert not decision.approved
    assert decision.reason == "claude_skip:weak_setup"


def test_claude_can_select_better_candidate(monkeypatch):
    monkeypatch.setattr("trade_ai.config.settings.CLAUDE_DECISION_ENABLED", True)
    monkeypatch.setattr("trade_ai.config.settings.ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "trade_ai.services.claude_decision._call_claude",
        lambda payload: {"action": "approve", "ticker": "NVDA", "confidence": 0.9, "reason": "cleaner_setup"},
    )

    weaker = _prediction(ticker="AAPL", p=0.72)
    stronger = _prediction(ticker="NVDA", p=0.71, reason="squeeze_breakout", squeeze=True, breakout="UP")
    decision = choose_signal_with_claude([weaker, stronger], lambda ticker: (7, 10))

    assert decision.approved
    assert decision.prediction is not None
    assert decision.prediction.ticker == "NVDA"
    assert decision.reason == "claude_approve:cleaner_setup"


def test_claude_full_control_can_override_local_skip(monkeypatch):
    monkeypatch.setattr("trade_ai.config.settings.CLAUDE_DECISION_ENABLED", True)
    monkeypatch.setattr("trade_ai.config.settings.CLAUDE_FULL_CONTROL_ENABLED", True)
    monkeypatch.setattr("trade_ai.config.settings.ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "trade_ai.services.claude_decision._call_claude",
        lambda payload: {"action": "approve", "ticker": "AAPL", "confidence": 0.75, "reason": "acceptable"},
    )

    tight_margin = _prediction(ticker="AAPL", p=0.44, threshold=0.42)
    decision = choose_signal_with_claude([tight_margin], lambda ticker: (7, 10))

    assert decision.approved
    assert decision.reason == "claude_approve:acceptable"
