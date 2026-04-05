import os, time, subprocess
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit("ERROR: BOT_TOKEN yoki CHAT_ID topilmadi (.env tekshir).")

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

WATCHLIST_FILE = Path("watchlist.txt")
COOLDOWN_SEC = 60
THRESHOLD = 0.60  # p >= 0.60 bo'lsa signal

last_sent_key = ""

def tg_send(text: str):
    r = requests.post(
        f"{BASE}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=20
    )
    return r.status_code, r.text

def load_watchlist():
    if not WATCHLIST_FILE.exists():
        WATCHLIST_FILE.write_text("SPY\nAAPL\nMSFT\nNVDA\nTSLA\nMETA\nAMZN\nGOOGL\nXLK\n", encoding="utf-8")
    tickers = []
    for line in WATCHLIST_FILE.read_text(encoding="utf-8").splitlines():
        t = line.strip().upper()
        if t and not t.startswith("#"):
            tickers.append(t)
    return tickers

def run_multi_predict():
    # Sizda oldindan bor: multi_predict.py
    # U stdout qaytaradi: "AAPL: BUY (p=0.67, th=0.33, side=BUY)" kabi
    p = subprocess.run(
        [os.sys.executable, "multi_predict.py", "--auto"],
        capture_output=True,
        text=True,
        errors="ignore"
    )
    return p.stdout

def parse_best(lines: str, tickers: list[str]):
    best = None
    best_prob = -1.0
    best_sig = ""

    for line in lines.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue

        left, right = line.split(":", 1)
        ticker = left.strip().upper()
        if ticker not in tickers:
            continue

        # p=0.67 ni topamiz
        prob = None
        if "p=" in right:
            try:
                prob = float(right.split("p=")[1].split(")")[0].split(",")[0].strip())
            except:
                prob = None

        sig = right.strip().split("(")[0].strip().upper()  # BUY/SELL/HOLD/STRONG_BUY...

        # BUY/SELL bo'lsa o'zini ehtimoli: BUY => p, SELL => (1-p)
        if prob is None:
            continue

        if "SELL" in sig:
            eff = 1.0 - prob
            side = "SELL"
        elif "BUY" in sig:
            eff = prob
            side = "BUY"
        else:
            continue

        if eff >= THRESHOLD and eff > best_prob:
            best_prob = eff
            best = ticker
            best_sig = side

    if best:
        return best, best_sig, best_prob
    return None, None, None

def main():
    tickers = load_watchlist()
    print("ULTIMATE SIGNAL BOT started. Stop: CTRL+C")

    global last_sent_key

    while True:
        try:
            out = run_multi_predict()
            ticker, side, prob = parse_best(out, tickers)

            if ticker:
                msg = f"TOP SIGNAL\\nTicker: {ticker}\\nSide: {side}\\nConfidence: {prob:.2f}"
                key = f"{ticker}-{side}-{round(prob,2)}"

                if key != last_sent_key:
                    code, resp = tg_send(msg)
                    print(f"Sent {key} | TG={code}")
                    if code != 200:
                        print("TG RESP:", resp)
                    last_sent_key = key
            else:
                print("No strong signal...")

            time.sleep(COOLDOWN_SEC)

        except KeyboardInterrupt:
            print("Stopped.")
            break
        except Exception as e:
            print("ERROR:", repr(e))
            time.sleep(10)

if __name__ == "__main__":
    main()
