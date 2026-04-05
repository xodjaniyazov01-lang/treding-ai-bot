from __future__ import annotations

import json
import requests
from typing import Tuple

from ..config.settings import BOT_TOKEN, CHAT_ID

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _api(method: str) -> str:
    return f"{BASE}/{method}"


def send_signal_card(text: str, signal_id: str) -> Tuple[int, str]:
    """
    Signal yuboradi va WIN/LOSS tugmalarini chiqaradi.
    """
    payload = {
        "chat_id": CHAT_ID,
        "text": text + "\n\nNatija kiriting (faqat bitta marta):",
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
