from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# trade_ai paketini topishi uchun (PYTHONPATH bo'lmasa ham)
import sys
ROOT = Path(__file__).resolve().parents[3]  # .../trade_ai
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ..legacy import multi_predict, triple_confirm  # noqa: E402

# =========================
# TELEGRAM SETTINGS (read from .env)
# =========================
load_dotenv(ROOT / ".env")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHAT_ID = (os.getenv("CHAT_ID") or "").strip()

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit("BOT_TOKEN yoki CHAT_ID topilmadi. .env faylga BOT_TOKEN va CHAT_ID yozing.")

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
OFFSET_FILE = ROOT / ".tg_offset"

# ====== LOCAL SETTINGS ======
COOLDOWN_SEC = int(os.getenv("COOLDOWN_SEC", "60"))
NEED_CONFIRM = int(os.getenv("NEED_CONFIRM", "2"))


def tg_send(text: str):
    r = requests.post(
        f"{BASE}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=15,
    )
    return r.status_code, r.text


def tg_send_with_buttons(text: str):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "WIN ✅", "callback_data": "WIN"},
                {"text": "LOSS ❌", "callback_data": "LOSS"},
            ]
        ]
    }
    r = requests.post(
        f"{BASE}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "reply_markup": keyboard},
        timeout=15,
    )
    return r.status_code, r.text


def tg_get_updates():
    offset = 0
    if OFFSET_FILE.exists():
        try:
            offset = int(OFFSET_FILE.read_text().strip())
        except Exception:
            offset = 0

    params = {"timeout": 0}
    if offset:
        params["offset"] = offset

    r = requests.get(f"{BASE}/getUpdates", params=params, timeout=20)
    data = r.json()

    # update offset
    if data.get("ok") and data.get("result"):
        last_id = data["result"][-1]["update_id"]
        OFFSET_FILE.write_text(str(last_id + 1))

    return data


def tg_answer_callback(callback_query_id: str, text: str):
    requests.post(
        f"{BASE}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id, "text": text},
        timeout=10,
    )


def should_alert(final_text: str) -> bool:
    t = final_text.upper()
    return t.startswith("BUY") or t.startswith("SELL") or t.startswith("CONFLICT")


def write_feedback(data: str):
    log = ROOT / "feedback_log.csv"
    if not log.exists():
        log.write_text("ts,final,feedback\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.utcnow().isoformat()},{data.replace(',', ';')},1\n")


def auto_train():
    # optional: trigger training pipeline if you want
    return


def compute_final(need: int) -> tuple[str, str]:
    tickers = multi_predict.load_watchlist()
    signals = triple_confirm.get_signals(tickers)

    if not signals:
        return "", ""

    buy_count = 0
    sell_count = 0

    spy_sig, spy_p = signals.get("SPY", ("HOLD", 0.0))

    for sig, _p in signals.values():
        if sig in ("BUY", "STRONG_BUY"):
            buy_count += 1
        elif sig in ("SELL", "STRONG_SELL"):
            sell_count += 1

    market = "HOLD"
    if spy_sig in ("BUY", "STRONG_BUY"):
        market = "BUY"
    elif spy_sig in ("SELL", "STRONG_SELL"):
        market = "SELL"

    market_line = f"MARKET: {spy_sig}({spy_p:.2f}) => {market}"

    final = "HOLD"
    if buy_count >= need and sell_count == 0:
        final = "BUY"
    elif sell_count >= need and buy_count == 0:
        final = "SELL"
    elif buy_count >= need and sell_count >= 1:
        final = "CONFLICT"
    elif market != "HOLD":
        final = f"{market} (Market)"

    final_line = f"FINAL: {final} (need={need}, buy={buy_count}, sell={sell_count}, total={len(signals)})"
    return final_line, market_line


def main():
    print("REALTIME WATCH PRO started. Stop: CTRL+C")
    last_sent = ""
    last_sent_time = 0.0

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        final, market_line = compute_final(NEED_CONFIRM)

        if not final:
            print(f"{now} | FINAL=")
            tg_send("⚠️ realtime_watch_pro: FINAL topilmadi.")
            time.sleep(20)
            continue

        print(f"{now} | {final}")

        # Telegram alert
        if should_alert(final):
            is_same = (final == last_sent)
            can_send = (time.time() - last_sent_time) >= COOLDOWN_SEC

            if (not is_same) or can_send:
                msg = f"{final}\n{market_line}\nTIME: {now}\n\nNatija kiriting:"
                code, _ = tg_send_with_buttons(msg)
                print(f"Telegram sent: {code}")
                last_sent = final
                last_sent_time = time.time()

        # Tugmalar
        updates = tg_get_updates()
        if updates.get("ok"):
            for upd in updates.get("result", []):
                cq = upd.get("callback_query")
                if not cq:
                    continue
                cq_id = cq.get("id")
                data = cq.get("data")
                if data in ("WIN", "LOSS"):
                    write_feedback(data)
                    auto_train()
                    tg_answer_callback(cq_id, f"Saved: {data}")
                    print(f"Button saved: {data}")

        time.sleep(20)


if __name__ == "__main__":
    main()
