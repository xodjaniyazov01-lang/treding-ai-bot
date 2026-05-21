from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

from trade_ai.utils.helpers import parse_bool

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
ARCHIVE_DIR = PROJECT_ROOT / "archive"

ENV_PATH = Path(os.getenv("TRADE_AI_ENV", str(PROJECT_ROOT / ".env")))
if load_dotenv is not None:
    load_dotenv(ENV_PATH)

MODEL_PATH = PROJECT_ROOT / "model.joblib"
TRAINING_DATA_PATH = DATA_DIR / "patterns.csv"
THRESHOLD_PATH = DATA_DIR / "threshold.txt"
WATCHLIST_PATH = DATA_DIR / "watchlist.txt"
WATCH_STATE_PATH = DATA_DIR / "watch_state.json"
SIGNALS_DB_PATH = DATA_DIR / "signals_history.db"
YF_CACHE_DIR = DATA_DIR / "yf_cache"
FUNDAMENTALS_CACHE_PATH = DATA_DIR / "fundamentals_cache.json"
LOG_DIR = DATA_DIR / "logs"
BOT_LOG_PATH = LOG_DIR / "bot.log"
BOT_ERR_LOG_PATH = LOG_DIR / "bot.err.log"

DEFAULT_TF_LABEL = "M5"
TF_MAP = {
    "M5": ("5m", "10d"),
    "M15": ("15m", "30d"),
    "H1": ("60m", "180d"),
    "H4": ("4h", "730d"),
}

DEFAULT_THRESHOLD = float(os.getenv("DEFAULT_THRESHOLD", "0.60"))
THRESHOLD_MIN = 0.40
THRESHOLD_MAX = 0.75
SLEEP_SEC = int(os.getenv("SLEEP_SEC", "60"))
DUPLICATE_TTL_SEC = int(os.getenv("DUPLICATE_TTL_SEC", "300"))

YF_SINGLE_TIMEOUT_SEC = 8
YF_BATCH_TIMEOUT_SEC = 14
YF_RETRIES = 3
YF_ENTRY_MIN_ROWS = 60
YF_SIGNAL_MIN_ROWS = 80
YF_TREND_MIN_ROWS = 120
YF_DAILY_MIN_ROWS = 260

TELEGRAM_TIMEOUT_SEC = 12
TELEGRAM_POLL_TIMEOUT_SEC = 10
TELEGRAM_LOG_LEVEL = os.getenv("TELEGRAM_LOG_LEVEL", "WARNING").upper()
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "7"))

VIX_HIGH_THRESHOLD = 30.0

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


def require_telegram() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "BOT_TOKEN/CHAT_ID topilmadi. .env ni tekshiring: "
            f"{ENV_PATH} (yoki environment orqali berilsin)"
        )
