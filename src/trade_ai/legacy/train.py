from __future__ import annotations
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    average_precision_score,
    precision_recall_curve,
)
from sklearn.linear_model import LogisticRegression

# ✅ hamma fayllar PROJECT ROOT’da bo‘lsin (multi_predict ham shuni o‘qiydi)
ROOT = Path(__file__).resolve().parents[3]  # .../trade_ai
CSV_PATH = ROOT / "patterns.csv"
MODEL_PATH = ROOT / "model.joblib"
THRESH_PATH = ROOT / "threshold.txt"

TARGET = "label"

FEATURES = [
    "pattern_name",
    "side",
    "st_3m",
    "st_1h",
    "st_4h",
    "trend_align",
    "is_consolidation",
    "breakout",
    "volume_spike",
    "neckline_break",
    "atr_ratio",
    "rsi",
    "close_vs_ema",
]

CAT = ["pattern_name", "side"]
NUM = [c for c in FEATURES if c not in CAT]

def load_data():
    if not CSV_PATH.exists():
        raise SystemExit(f"❌ patterns.csv topilmadi: {CSV_PATH}")

    df = pd.read_csv(CSV_PATH)

    df = df.dropna(subset=FEATURES + [TARGET]).copy()
    df[TARGET] = pd.to_numeric(df[TARGET], errors="coerce")
    df = df.dropna(subset=[TARGET])
    df[TARGET] = df[TARGET].astype(int)

    for c in NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=NUM).copy()

    return df

def build_model():
    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CAT),
            ("num", "passthrough", NUM),
        ]
    )

    clf = LogisticRegression(
        max_iter=500,
        class_weight="balanced"
    )

    return Pipeline([("pre", pre), ("clf", clf)])

def pick_best_threshold(y_true, proba):
    precisions, recalls, thresholds = precision_recall_curve(y_true, proba)
    thresholds = np.append(thresholds, 1.0)

    f1 = (2 * precisions * recalls) / (precisions + recalls + 1e-9)
    best_i = int(np.argmax(f1))
    return float(thresholds[best_i]), float(f1[best_i]), float(precisions[best_i]), float(recalls[best_i])

def main():
    df = load_data()

    counts = df[TARGET].value_counts().to_dict()
    print("Label counts:", counts)
    if len(counts) < 2:
        print("❌ Data ichida faqat bitta label bor.")
        return

    X = df[FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=0.30,
        random_state=42,
        stratify=y
    )

    model = build_model()
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1]
    best_th, best_f1, best_p, best_r = pick_best_threshold(y_test.values, proba)

    roc = roc_auc_score(y_test, proba)
    pr = average_precision_score(y_test, proba)
    preds = (proba >= best_th).astype(int)

    print("\n=== AUTO THRESHOLD FOUND ===")
    print(f"Best threshold: {best_th:.3f} | F1={best_f1:.3f} | Precision={best_p:.3f} | Recall={best_r:.3f}")

    print("\n=== HOLDOUT REPORT ===")
    print("Train rows:", len(X_train), " Test rows:", len(X_test))
    print(classification_report(y_test, preds, digits=2))
    print(f"ROC AUC: {roc:.3f}")
    print(f"PR  AUC: {pr:.3f}")

    joblib.dump(model, MODEL_PATH)
    THRESH_PATH.write_text(str(best_th), encoding="utf-8")

    print(f"\n✅ Model saqlandi: {MODEL_PATH}")
    print(f"✅ Threshold saqlandi: {THRESH_PATH} ({best_th:.3f})")

if __name__ == "__main__":
    main()
