from __future__ import annotations

import json
from typing import Tuple

import requests

from ..config.settings import BOT_TOKEN, CHAT_ID, require_telegram


def _base() -> str:
    require_telegram()
    return f"https://api.telegram.org/bot{BOT_TOKEN}"


def _api(method: str) -> str:
    return f"{_base()}/{method}"


def send_signal_card(text: str, signal_id: str) -> Tuple[int, str]:
    """Signal yuboradi va WIN/LOSS tugmalarini chiqaradi."""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
        "reply_markup": json.dumps(
            {
                "inline_keyboard": [
                    [{"text": "WIN ✅", "callback_data": f"WIN:{signal_id}"}],
                    [{"text": "LOSS ❌", "callback_data": f"LOSS:{signal_id}"}],
                ]
            }
        ),
    }
    r = requests.post(_api("sendMessage"), data=payload, timeout=20)
    return r.status_code, r.text
