import csv
import os
import time

BULK = "patterns_bulk.csv"
TRADES = "trades_log.csv"

FIELDS = [
    "pattern_name","side","st_3m","st_1h","st_4h","trend_align","is_consolidation",
    "breakout","volume_spike","neckline_break","atr_ratio","rsi","close_vs_ema","label"
]

def ensure_file(path, header):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)

def ask(prompt, default=None):
    v = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
    return default if (v == "" and default is not None) else v

def ask_int(prompt, default):
    return int(ask(prompt, str(default)))

def ask_float(prompt, default):
    return float(ask(prompt, str(default)))

def main():
    ensure_file(BULK, FIELDS)
    ensure_file(TRADES, ["ts","ticker"] + FIELDS + ["notes"])

    print("🧾 Trade natijasi (WIN/LOSS) ni yozamiz. Bu AI'ga o'rganishga yordam beradi.\n")

    ticker = ask("ticker (SPY/AAPL/XLK/...)","AAPL")
    row = {
        "pattern_name": ask("pattern_name","bull_flag"),
        "side": ask("side (BUY/SELL)","BUY"),
        "st_3m": ask_int("st_3m (BUY=1 SELL=0)", 1),
        "st_1h": ask_int("st_1h", 1),
        "st_4h": ask_int("st_4h", 1),
        "trend_align": ask_int("trend_align", 1),
        "is_consolidation": ask_int("is_consolidation", 0),
        "breakout": ask_int("breakout", 1),
        "volume_spike": ask_int("volume_spike", 1),
        "neckline_break": ask_int("neckline_break", 0),
        "atr_ratio": ask_float("atr_ratio (ATR/Close)", 0.005),
        "rsi": ask_float("rsi (0-100)", 60),
        "close_vs_ema": ask_int("close_vs_ema (above=1 below=0)", 1),
        "label": ask_int("label (WIN=1 LOSS=0)", 1),
    }
    notes = ask("notes (ixtiyoriy)", "")

    # 1) trades_log.csv ga yozamiz
    with open(TRADES, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([int(time.time()), ticker] + [row[k] for k in FIELDS] + [notes])

    # 2) patterns_bulk.csv ga ham qo‘shamiz (model qayta o‘qishi uchun)
    with open(BULK, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([row[k] for k in FIELDS])

    print(f"\n✅ Yozildi: {TRADES}")
    print(f"✅ Bulk qo‘shildi: {BULK}")
    print("👉 Agar auto_train.py ishlayotgan bo‘lsa, model avtomatik qayta o‘qiydi.")

if __name__ == "__main__":
    main()
