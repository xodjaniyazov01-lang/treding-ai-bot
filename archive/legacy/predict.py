import os
import joblib
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "model.joblib")
THRESH_PATH = os.path.join(HERE, "threshold.txt")

def load_threshold(default=0.60):
    if os.path.exists(THRESH_PATH):
        try:
            return float(open(THRESH_PATH, "r", encoding="utf-8").read().strip())
        except:
            pass
    return default

def predict_one(sample: dict):
    model = joblib.load(MODEL_PATH)
    df = pd.DataFrame([sample])
    p = float(model.predict_proba(df)[0][1])

    th = load_threshold()

    if p >= max(0.85, th + 0.15):
        return "STRONG_BUY", p, th
    if p >= th:
        return "BUY", p, th
    if p <= min(0.15, th - 0.15):
        return "STRONG_SELL", p, th
    if p < (th - 0.10):
        return "SELL", p, th
    return "HOLD", p, th

def main():
    # auto sample (sening tiziming uchun)
    sample = {
        "pattern_name": "auto_pattern",
        "side": "BUY",
        "st_3m": 1,
        "st_1h": 1,
        "st_4h": 1,
        "trend_align": 1,
        "is_consolidation": 0,
        "breakout": 1,
        "volume_spike": 1,
        "neckline_break": 0,
        "atr_ratio": 0.005,
        "rsi": 60,
        "close_vs_ema": 1,
    }

    sig, p, th = predict_one(sample)
    print(f"{sig} (p={p:.2f}, threshold={th:.2f})")

if __name__ == "__main__":
    main()
