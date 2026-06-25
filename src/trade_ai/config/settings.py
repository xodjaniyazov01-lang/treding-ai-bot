from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

from trade_ai.utils.helpers import parse_bool, parse_float

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
ARCHIVE_DIR = PROJECT_ROOT / "archive"

ENV_PATH = Path(os.getenv("TRADE_AI_ENV", str(PROJECT_ROOT / ".env")))
if load_dotenv is not None:
    load_dotenv(ENV_PATH)

MODEL_PATH = PROJECT_ROOT / "model.joblib"
TRAINING_DATA_PATH = DATA_DIR / "patterns.csv"
PATTERNS_BULK_PATH = DATA_DIR / "patterns_bulk.csv"
FEEDBACK_LOG_PATH = PROJECT_ROOT / "feedback_log.csv"
FEEDBACK_PENDING_PATH = DATA_DIR / "pending_feedback.json"
SIGNALS_CSV_PATH = PROJECT_ROOT / "signals.csv"
SIGNALS_LOG_PATH = PROJECT_ROOT / "signals.log"
THRESHOLD_PATH = DATA_DIR / "threshold.txt"
WATCHLIST_PATH = DATA_DIR / "watchlist.txt"
WATCH_STATE_PATH = DATA_DIR / "watch_state.json"
SIGNALS_DB_PATH = DATA_DIR / "signals_history.db"
YF_CACHE_DIR = DATA_DIR / "yf_cache"
FUNDAMENTALS_CACHE_PATH = DATA_DIR / "fundamentals_cache.json"
LOG_DIR = DATA_DIR / "logs"
BOT_LOG_PATH = LOG_DIR / "bot.log"
BOT_ERR_LOG_PATH = LOG_DIR / "bot.err.log"
BACKTEST_RESULTS_PATH = DATA_DIR / "backtest_results.json"
TRAINING_METRICS_PATH = DATA_DIR / "training_metrics.json"

DEFAULT_TF_LABEL = "M5"
TF_MAP = {
    "M5": ("5m", "10d"),
    "M15": ("15m", "30d"),
    "H1": ("60m", "180d"),
    "H4": ("4h", "730d"),
}

DEFAULT_THRESHOLD = float(os.getenv("DEFAULT_THRESHOLD", "0.60"))
THRESHOLD_MIN = float(os.getenv("THRESHOLD_MIN", "0.40"))
THRESHOLD_MAX = float(os.getenv("THRESHOLD_MAX", "0.75"))
SLEEP_SEC = int(os.getenv("SLEEP_SEC", "60"))
DUPLICATE_TTL_SEC = int(os.getenv("DUPLICATE_TTL_SEC", "300"))
SIGNAL_COOLDOWN_SEC = int(os.getenv("SIGNAL_COOLDOWN_SEC", str(DUPLICATE_TTL_SEC)))

YF_SINGLE_TIMEOUT_SEC = int(os.getenv("YF_SINGLE_TIMEOUT_SEC", "8"))
YF_BATCH_TIMEOUT_SEC = int(os.getenv("YF_BATCH_TIMEOUT_SEC", "14"))
YF_RETRIES = int(os.getenv("YF_RETRIES", "3"))
YF_ENTRY_MIN_ROWS = int(os.getenv("YF_ENTRY_MIN_ROWS", "60"))
YF_SIGNAL_MIN_ROWS = int(os.getenv("YF_SIGNAL_MIN_ROWS", "80"))
YF_TREND_MIN_ROWS = int(os.getenv("YF_TREND_MIN_ROWS", "120"))
YF_DAILY_MIN_ROWS = int(os.getenv("YF_DAILY_MIN_ROWS", "260"))

TELEGRAM_TIMEOUT_SEC = int(os.getenv("TELEGRAM_TIMEOUT_SEC", "12"))
TELEGRAM_POLL_TIMEOUT_SEC = int(os.getenv("TELEGRAM_POLL_TIMEOUT_SEC", "10"))
TELEGRAM_LOG_LEVEL = os.getenv("TELEGRAM_LOG_LEVEL", "WARNING").upper()
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "7"))
DAILY_REPORT_TIME = os.getenv("DAILY_REPORT_TIME", "20:00").strip() or "20:00"
AUTO_RETRAIN_FEEDBACK_STEP = int(os.getenv("AUTO_RETRAIN_FEEDBACK_STEP", "50"))
AI_DECISION_ENABLED = parse_bool(os.getenv("AI_DECISION_ENABLED"), default=True)
AI_MIN_DECISION_SCORE = parse_float(os.getenv("AI_MIN_DECISION_SCORE"), 0.55) or 0.55
AI_MIN_PROBA_MARGIN = parse_float(os.getenv("AI_MIN_PROBA_MARGIN"), 0.03) or 0.03
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
CLAUDE_DECISION_ENABLED = parse_bool(os.getenv("CLAUDE_DECISION_ENABLED"), default=False)
CLAUDE_FULL_CONTROL_ENABLED = parse_bool(os.getenv("CLAUDE_FULL_CONTROL_ENABLED"), default=False)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest").strip() or "claude-3-5-sonnet-latest"
CLAUDE_TIMEOUT_SEC = int(os.getenv("CLAUDE_TIMEOUT_SEC", "12"))
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "160"))
CLAUDE_TOP_N = int(os.getenv("CLAUDE_TOP_N", "8"))
CLAUDE_MIN_CONFIDENCE = parse_float(os.getenv("CLAUDE_MIN_CONFIDENCE"), 0.60) or 0.60

VIX_HIGH_THRESHOLD = parse_float(os.getenv("VIX_HIGH_THRESHOLD"), 30.0) or 30.0
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
BACKTEST_HOLD_BARS = int(os.getenv("BACKTEST_HOLD_BARS", "24"))
BACKTEST_MAX_SIGNALS_PER_TICKER = int(os.getenv("BACKTEST_MAX_SIGNALS_PER_TICKER", "50"))

TEST_MODE = parse_bool(os.getenv("TEST_MODE"), default=False)
TEST_TICKERS = [
    item.strip().upper()
    for item in os.getenv("TEST_TICKERS", "AAPL,TSLA,NVDA,MSFT,AMZN,META,SPY").replace(";", ",").split(",")
    if item.strip()
]
IGNORE_THRESHOLD_IN_TEST = parse_bool(os.getenv("IGNORE_THRESHOLD_IN_TEST"), default=False)
FORCE_SIGNAL_IN_TEST = parse_bool(os.getenv("FORCE_SIGNAL_IN_TEST"), default=False)

PATTERN_TARGET = "label"
PATTERN_FEATURES = [
    "pattern_name",
    "side",
    "st_3m",
    "st_1h",
    "st_4h",
    "trend_align",
    "is_consolidation",
    "breakout",
    "volume_spike",
    "neckline_break",
    "atr_ratio",
    "rsi",
    "close_vs_ema",
]
PATTERN_CATEGORICAL = ["pattern_name", "side"]

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHAT_ID = (os.getenv("CHAT_ID") or "").strip()
MODEL_VERSION = os.getenv("MODEL_VERSION", MODEL_PATH.name).strip() or MODEL_PATH.name
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "yfinance").strip() or "yfinance"
ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY", "10000"))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))
MAX_OPEN_SIGNALS = int(os.getenv("MAX_OPEN_SIGNALS", "3"))
MAX_TICKER_EXPOSURE_PCT = float(os.getenv("MAX_TICKER_EXPOSURE_PCT", "0.02"))


def require_telegram() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "BOT_TOKEN/CHAT_ID topilmadi. .env ni tekshiring: "
            f"{ENV_PATH} (yoki environment orqali berilsin)"
        )
