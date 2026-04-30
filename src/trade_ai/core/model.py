from __future__ import annotations

from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, classification_report, precision_recall_curve, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from trade_ai.config import settings

FEATURES = list(settings.PATTERN_FEATURES)
CATEGORICAL = list(settings.PATTERN_CATEGORICAL)
NUMERICAL = [column for column in FEATURES if column not in CATEGORICAL]


@dataclass
class TrainingResult:
    rows: int
    train_rows: int
    test_rows: int
    best_threshold: float
    best_f1: float
    best_precision: float
    best_recall: float
    roc_auc: float
    pr_auc: float
    report: str
    label_counts: dict


def load_training_data() -> pd.DataFrame:
    if not settings.TRAINING_DATA_PATH.exists():
        raise FileNotFoundError(f"patterns dataset topilmadi: {settings.TRAINING_DATA_PATH}")
    df = pd.read_csv(settings.TRAINING_DATA_PATH)
    df = df.dropna(subset=FEATURES + [settings.PATTERN_TARGET]).copy()
    df[settings.PATTERN_TARGET] = pd.to_numeric(df[settings.PATTERN_TARGET], errors="coerce")
    df = df.dropna(subset=[settings.PATTERN_TARGET]).copy()
    df[settings.PATTERN_TARGET] = df[settings.PATTERN_TARGET].astype(int)
    for column in NUMERICAL:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.dropna(subset=NUMERICAL).copy()


def build_model() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            ("num", "passthrough", NUMERICAL),
        ]
    )
    clf = LogisticRegression(max_iter=500, class_weight="balanced")
    return Pipeline([("pre", preprocessor), ("clf", clf)])


def pick_best_threshold(y_true, proba) -> tuple[float, float, float, float]:
    precisions, recalls, thresholds = precision_recall_curve(y_true, proba)
    thresholds = np.append(thresholds, 1.0)
    f1 = (2 * precisions * recalls) / (precisions + recalls + 1e-9)
    best_index = int(np.argmax(f1))
    return (
        float(thresholds[best_index]),
        float(f1[best_index]),
        float(precisions[best_index]),
        float(recalls[best_index]),
    )


def train_and_save() -> TrainingResult:
    df = load_training_data()
    label_counts = df[settings.PATTERN_TARGET].value_counts().to_dict()
    if len(label_counts) < 2:
        raise ValueError("data ichida faqat bitta label bor")

    x_data = df[FEATURES]
    y_data = df[settings.PATTERN_TARGET]
    x_train, x_test, y_train, y_test = train_test_split(
        x_data,
        y_data,
        test_size=0.30,
        random_state=42,
        stratify=y_data,
    )

    model = build_model()
    model.fit(x_train, y_train)
    proba = model.predict_proba(x_test)[:, 1]
    best_th, best_f1, best_p, best_r = pick_best_threshold(y_test.values, proba)
    preds = (proba >= best_th).astype(int)
    roc = roc_auc_score(y_test, proba)
    pr = average_precision_score(y_test, proba)
    report = classification_report(y_test, preds, digits=2)

    joblib.dump(model, settings.MODEL_PATH)
    settings.THRESHOLD_PATH.write_text(f"{best_th:.4f}", encoding="utf-8")

    return TrainingResult(
        rows=len(df),
        train_rows=len(x_train),
        test_rows=len(x_test),
        best_threshold=best_th,
        best_f1=best_f1,
        best_precision=best_p,
        best_recall=best_r,
        roc_auc=float(roc),
        pr_auc=float(pr),
        report=report,
        label_counts=label_counts,
    )
