import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "patterns.csv")

FIELDS = [
    "pattern_name","side","st_3m","st_1h","st_4h","trend_align",
    "is_consolidation","breakout","volume_spike","neckline_break",
    "atr_ratio","rsi","close_vs_ema","label"
]

def ask(name, default):
    v = input(f"{name} [{default}]: ").strip()
    return default if v == "" else v

def main():
    print("\n⚡ FAST PATTERN ADD (faqat muhimlari)\n")

    pattern = ask("pattern (bull_flag / head_shoulders / triangle)", "bull_flag")
    side = ask("side (BUY/SELL)", "BUY")
    result = ask("natija (WIN/LOSS)", "WIN")

    row = {
        "pattern_name": pattern.lower(),
        "side": side.upper(),

        # 🧠 Model o‘zi to‘ldiradi (default)
        "st_3m": 1 if side.upper()=="BUY" else 0,
        "st_1h": 1 if side.upper()=="BUY" else 0,
        "st_4h": 1 if side.upper()=="BUY" else 0,
        "trend_align": 1,
        "is_consolidation": 0,
        "breakout": 1,
        "volume_spike": 1,
        "neckline_break": 1 if "head" in pattern else 0,
        "atr_ratio": 0.005,
        "rsi": 60 if side.upper()=="BUY" else 40,
        "close_vs_ema": 1 if side.upper()=="BUY" else 0,
        "label": 1 if result.upper()=="WIN" else 0,
    }

    file_exists = os.path.exists(CSV)
    with open(CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not file_exists or os.path.getsize(CSV) == 0:
            writer.writeheader()
        writer.writerow(row)

    print("✅ Qo‘shildi:", row)

if __name__ == "__main__":
    main()
