from __future__ import annotations
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

ROOT = Path(__file__).resolve().parents[2]   # .../src/trade_ai
ENV_PATH = ROOT.parent / ".env"              # .../src/.env emas, balki project root/.env

if load_dotenv is not None:
    load_dotenv(ENV_PATH)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()

if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError(
        f"BOT_TOKEN/CHAT_ID topilmadi. .env tekshir: {ENV_PATH}\n"
        f"BOT_TOKEN='{BOT_TOKEN}' CHAT_ID='{CHAT_ID}'"
    )
