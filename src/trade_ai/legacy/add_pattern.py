import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "patterns.csv")

FIELDS = [
    "pattern_name","side","st_3m","st_1h","st_4h","trend_align",
    "is_consolidation","breakout","volume_spike","neckline_break",
    "atr_ratio","rsi","close_vs_ema","label"
]

def ask(name, default):
    v = input(f"{name} [{default}]: ").strip()
    return default if v == "" else v

def ask_int(name, default):
    return int(ask(name, str(default)))

def ask_float(name, default):
    return float(ask(name, str(default)))

def main():
    print("📝 Yangi pattern qo‘shish (Enter = default)\n")
    row = {
        "pattern_name": ask("pattern_name (bull_flag/head_shoulders/...)", "bull_flag").lower(),
        "side": ask("side (BUY/SELL)", "BUY").upper(),
        "st_3m": ask_int("st_3m (BUY=1, SELL=0)", 1),
        "st_1h": ask_int("st_1h (BUY=1, SELL=0)", 1),
        "st_4h": ask_int("st_4h (BUY=1, SELL=0)", 1),
        "trend_align": ask_int("trend_align (1H==4H ? 1 : 0)", 1),
        "is_consolidation": ask_int("is_consolidation (yes=1,no=0)", 0),
        "breakout": ask_int("breakout (yes=1,no=0)", 1),
        "volume_spike": ask_int("volume_spike (yes=1,no=0)", 1),
        "neckline_break": ask_int("neckline_break (yes=1,no=0)", 0),
        "atr_ratio": ask_float("atr_ratio (ATR/Close)", 0.005),
        "rsi": ask_float("rsi (0-100)", 60),
        "close_vs_ema": ask_int("close_vs_ema (above=1, below=0)", 1),
        "label": ask_int("label (WIN=1, LOSS=0)", 1),
    }

    file_exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not file_exists or os.path.getsize(CSV_PATH) == 0:
            writer.writeheader()
        writer.writerow(row)

    print("\n✅ Qo‘shildi:", row)
    print("📄 File:", CSV_PATH)

if __name__ == "__main__":
    main()
