from pathlib import Path
import subprocess, time, os
import requests
from datetime import datetime

from dotenv import load_dotenv

# =========================
# TELEGRAM SETTINGS (read from .env)
# =========================
# .env example:
# BOT_TOKEN=123456:ABCDEF...
# CHAT_ID=1106940684
load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHAT_ID = (os.getenv("CHAT_ID") or "").strip()

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit("BOT_TOKEN yoki CHAT_ID topilmadi. .env faylga BOT_TOKEN va CHAT_ID yozing.")

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
OFFSET_FILE = Path(".tg_offset")

# ====== LOCAL SETTINGS ======
COOLDOWN_SEC = int(os.getenv("COOLDOWN_SEC", "60"))
NEED_CONFIRM = int(os.getenv("NEED_CONFIRM", "2"))

# telegramga yuborishda signal_id ber
# send_signal_card(text, signal_id)

def tg_send(text: str):
    r = requests.post(
        f"{BASE}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=15
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
        timeout=15
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
        timeout=10
    )


def should_alert(final_text: str):
    t = final_text.upper()
    if t.startswith("BUY") or t.startswith("SELL") or t.startswith("CONFLICT"):
        return True
    return False


def write_feedback(data: str):
    # append feedback
    log = Path("feedback_log.csv")
    if not log.exists():
        log.write_text("ts,final,feedback\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.utcnow().isoformat()},{data.replace(',', ';')},1\n")


def auto_train():
    # optional: trigger training pipeline if you want
    # subprocess.run(["python", "train.py"], check=False)
    return


def run_triple_confirm():
    # call triple_confirm.py to get final
    p = subprocess.run(
        ["python", "triple_confirm.py", "--auto", "--need", str(NEED_CONFIRM)],
        capture_output=True,
        text=True,
        shell=False,
    )
    out = (p.stdout or "") + (p.stderr or "")

    # find FINAL line
    final = ""
    market_line = ""
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("✅ FINAL:"):
            final = s.replace("✅ FINAL:", "").strip()
        if s.startswith("✅ MARKET:"):
            market_line = s.replace("✅ MARKET:", "").strip()

    return final, market_line, out


def main():
    print("REALTIME WATCH PRO started. Stop: CTRL+C")
    last_sent = ""
    last_sent_time = 0.0

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        final, market_line, out = run_triple_confirm()

        if not final:
            print(f"{now} | FINAL=")
            print("⚠️ DEBUG: triple_confirm output:\n" + out.strip())
            tg_send("⚠️ realtime_watch_pro: FINAL topilmadi. Terminalda DEBUG chiqdi.")
            time.sleep(20)
            continue

        print(f"{now} | FINAL={final}")

        # Telegram alert
        if should_alert(final):
            is_same = (final == last_sent)
            can_send = (time.time() - last_sent_time) >= COOLDOWN_SEC

            if (not is_same) or can_send:
                msg = f"FINAL: {final}\n{market_line}\nTIME: {now}\n\nNatija kiriting:"
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
