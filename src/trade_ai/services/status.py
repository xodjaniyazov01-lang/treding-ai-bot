from __future__ import annotations

import json
from datetime import datetime
from html import escape

from trade_ai.config import settings
from trade_ai.core.model import load_training_metrics
from trade_ai.core.strategy import get_model_status, read_threshold
from trade_ai.services.auto_retrain import retrain_progress


def _read_json(path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _fmt_float(value: object, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "N/A"


def _yes_no(value: bool) -> str:
    return "OK" if value else "NO"


def build_status_message(now: datetime | None = None) -> str:
    now = now or datetime.now()
    model = get_model_status()
    metrics = load_training_metrics()
    backtest = _read_json(settings.BACKTEST_RESULTS_PATH)
    progress = retrain_progress()

    loaded = _yes_no(bool(model.get("loaded")))
    model_exists = _yes_no(bool(model.get("exists")))
    db_exists = _yes_no(settings.SIGNALS_DB_PATH.exists())
    csv_exists = _yes_no(settings.SIGNALS_CSV_PATH.exists())
    log_exists = _yes_no(settings.SIGNALS_LOG_PATH.exists())
    backtest_exists = _yes_no(bool(backtest))

    lines = [
        "<b>Trade AI Status</b>",
        "",
        f"Updated: <code>{escape(now.strftime('%Y-%m-%d %H:%M:%S'))}</code>",
        f"Model: <code>{loaded}</code> / file <code>{model_exists}</code>",
        f"Model type: <code>{escape(str(model.get('model_type') or '-'))}</code>",
        f"Threshold: <code>{read_threshold():.4f}</code>",
        f"Model F1: <code>{_fmt_float(metrics.get('best_f1'))}</code>",
        f"Training rows: <code>{int(metrics.get('rows', 0) or 0)}</code>",
        f"Last retrain: <code>{escape(str(metrics.get('trained_at') or 'N/A'))}</code>",
        "",
        "<b>Feedback</b>",
        f"Rows: <code>{progress['count']}</code>",
        f"Progress: <code>{progress['delta']}/{progress['step']}</code>",
        f"Until retrain: <code>{progress['remaining']}</code>",
        "",
        "<b>Backtest</b>",
        f"Signals: <code>{int(backtest.get('total_signals', 0) or 0)}</code>",
        f"Win rate: <code>{float(backtest.get('win_rate', 0.0) or 0.0) * 100:.1f}%</code>",
        f"Avg PnL: <code>{_fmt_float(backtest.get('avg_pnl_pct'), 2)}%</code>",
        f"Best ticker: <code>{escape(str(backtest.get('best_ticker') or 'N/A'))}</code>",
        f"Worst ticker: <code>{escape(str(backtest.get('worst_ticker') or 'N/A'))}</code>",
        "",
        "<b>Storage</b>",
        f"DB: <code>{db_exists}</code>",
        f"signals.csv: <code>{csv_exists}</code>",
        f"signals.log: <code>{log_exists}</code>",
        f"backtest_results.json: <code>{backtest_exists}</code>",
    ]
    error = model.get("error")
    if error:
        lines.append(f"Model error: <code>{escape(str(error))}</code>")
    return "\n".join(lines)
