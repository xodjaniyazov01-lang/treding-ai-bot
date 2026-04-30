import os
import requests
import subprocess
import time
from dotenv import load_dotenv

# ================= LOAD ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    raise ValueError("BOT_TOKEN yoki CHAT_ID topilmadi (.env tekshir)")

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ================= SETTINGS =================
COOLDOWN = 60
THRESHOLD = 0.60
last_signal = ""

# ===========================================

def tg_send(text):
    requests.post(
        f"{BASE}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=15
    )

def get_signal():
    p = subprocess.run(
        ["python", "multi_predict.py", "--auto"],
        capture_output=True,
        text=True
    )
    return p.stdout

def extract_strong(text):
    lines = text.splitlines()
    best = None
    best_p = 0

    for line in lines:
        if "(" in line and ")" in line:
            try:
                ticker = line.split(":")[0].strip()
                prob = float(line.split("p=")[1].split(")")[0])

                if prob > best_p:
                    best_p = prob
                    best = (ticker, prob)

            except:
                continue

    if best and best_p >= THRESHOLD:
        return best[0], best[1]

    return None

print("🟢 SIMPLE SIGNAL BOT STARTED")

while True:
    try:
        raw = get_signal()
        strong = extract_strong(raw)

        if strong:
            ticker, prob = strong
            signal_text = f"🔥 SIGNAL\n\nTicker: {ticker}\nConfidence: {prob:.2f}"

            if signal_text != last_signal:
                tg_send(signal_text)
                last_signal = signal_text
                print("Sent:", signal_text)

        time.sleep(COOLDOWN)

    except Exception as e:
        print("ERROR:", e)
        time.sleep(10)
