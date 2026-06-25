from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
from trade_ai.services.backtest import summarize_backtest
from trade_ai.utils.helpers import clamp

logger = logging.getLogger("trade_ai.model")

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
    sources: dict
    threshold_updated: bool
    model_updated: bool
    previous_best_f1: float | None
    previous_rows: int | None
    previous_threshold: float | None
    backtest_summary: dict


def _read_training_source(path: Path, required_columns: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(f"{path.name} required columns missing: {', '.join(missing)}")
    return df[required_columns].copy()


def _read_feedback_source(path: Path, required_columns: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    validation_columns = list(dict.fromkeys(required_columns + ["confidence"]))
    missing = [column for column in validation_columns if column not in df.columns]
    if missing:
        logger.warning("feedback_log.csv skipped: missing columns=%s", ",".join(missing))
        return pd.DataFrame(columns=required_columns)

    out = df.copy()
    before = len(out)
    out[settings.PATTERN_TARGET] = pd.to_numeric(out[settings.PATTERN_TARGET], errors="coerce")
    bad_label = ~out[settings.PATTERN_TARGET].isin([0, 1])
    if bad_label.any():
        logger.warning("feedback_log.csv: skipping %d rows with invalid label", int(bad_label.sum()))
        out = out[~bad_label].copy()

    confidence = pd.to_numeric(out["confidence"], errors="coerce")
    bad_confidence = confidence.isna() | (confidence < 0.0) | (confidence > 1.0)
    if bad_confidence.any():
        logger.warning("feedback_log.csv: skipping %d rows with invalid confidence", int(bad_confidence.sum()))
        out = out[~bad_confidence].copy()

    for column in NUMERICAL:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    bad_nan = out[required_columns].isna().any(axis=1)
    if bad_nan.any():
        logger.warning("feedback_log.csv: skipping %d rows with empty/NaN training values", int(bad_nan.sum()))
        out = out[~bad_nan].copy()

    skipped = before - len(out)
    if skipped:
        logger.warning("feedback_log.csv quality check skipped rows=%d kept=%d", skipped, len(out))
    return out[required_columns].copy()


def load_training_data() -> tuple[pd.DataFrame, dict]:
    required_columns = FEATURES + [settings.PATTERN_TARGET]
    frames: list[pd.DataFrame] = []
    sources: dict[str, object] = {}
    skipped: dict[str, str] = {}

    for path in (settings.TRAINING_DATA_PATH, settings.PATTERNS_BULK_PATH, settings.FEEDBACK_LOG_PATH):
        if not path.exists():
            continue
        try:
            if path == settings.FEEDBACK_LOG_PATH:
                source_df = _read_feedback_source(path, required_columns)
            else:
                source_df = _read_training_source(path, required_columns)
        except ValueError as exc:
            skipped[path.name] = str(exc)
            continue
        except Exception as exc:
            skipped[path.name] = str(exc)
            logger.warning("%s skipped: %s", path.name, exc)
            continue
        if source_df.empty:
            skipped[path.name] = "no valid rows"
            continue
        frames.append(source_df)
        sources[path.name] = len(source_df)

    if not frames:
        raise FileNotFoundError(f"training dataset topilmadi: {settings.TRAINING_DATA_PATH}")

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=FEATURES + [settings.PATTERN_TARGET]).copy()
    df[settings.PATTERN_TARGET] = pd.to_numeric(df[settings.PATTERN_TARGET], errors="coerce")
    df = df.dropna(subset=[settings.PATTERN_TARGET]).copy()
    df[settings.PATTERN_TARGET] = df[settings.PATTERN_TARGET].astype(int)
    for column in NUMERICAL:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    clean_df = df.dropna(subset=NUMERICAL).drop_duplicates().copy()
    if skipped:
        sources["_skipped"] = skipped
    return clean_df, sources


def load_training_metrics() -> dict:
    if not settings.TRAINING_METRICS_PATH.exists():
        return {}
    try:
        return json.loads(settings.TRAINING_METRICS_PATH.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


def save_training_metrics(metrics: dict) -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.TRAINING_METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


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


def train_and_save(feedback_count: int | None = None) -> TrainingResult:
    df, sources = load_training_data()
    backtest_summary = summarize_backtest()
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
    active_th = clamp(best_th, settings.THRESHOLD_MIN, settings.THRESHOLD_MAX)
    preds = (proba >= active_th).astype(int)
    roc = roc_auc_score(y_test, proba)
    pr = average_precision_score(y_test, proba)
    report = classification_report(y_test, preds, digits=2)

    previous_metrics = load_training_metrics()
    previous_best_f1_raw = previous_metrics.get("best_f1")
    try:
        previous_best_f1 = float(previous_best_f1_raw)
    except Exception:
        previous_best_f1 = None
    try:
        previous_rows = int(previous_metrics.get("rows"))
    except Exception:
        previous_rows = None
    try:
        previous_threshold = float(previous_metrics.get("best_threshold"))
    except Exception:
        previous_threshold = None

    model_updated = previous_best_f1 is None or best_f1 > previous_best_f1
    threshold_updated = model_updated
    if model_updated:
        joblib.dump(model, settings.MODEL_PATH)
        settings.THRESHOLD_PATH.write_text(f"{active_th:.4f}", encoding="utf-8")

    stored_best_f1 = best_f1 if model_updated else previous_best_f1
    stored_rows = len(df) if model_updated else previous_rows
    stored_threshold = active_th if model_updated else previous_threshold
    save_training_metrics(
        {
            "trained_at": datetime.now().isoformat(timespec="seconds"),
            "rows": stored_rows if stored_rows is not None else len(df),
            "train_rows": len(x_train),
            "test_rows": len(x_test),
            "best_threshold": stored_threshold if stored_threshold is not None else active_th,
            "best_f1": stored_best_f1 if stored_best_f1 is not None else best_f1,
            "previous_best_f1": previous_best_f1,
            "last_run_f1": best_f1,
            "last_run_rows": len(df),
            "threshold_updated": threshold_updated,
            "model_updated": model_updated,
            "best_precision": best_p,
            "best_recall": best_r,
            "roc_auc": float(roc),
            "pr_auc": float(pr),
            "label_counts": label_counts,
            "sources": sources,
            "backtest_summary": backtest_summary,
            "last_feedback_count": int(feedback_count) if feedback_count is not None else previous_metrics.get("last_feedback_count", 0),
        }
    )

    return TrainingResult(
        rows=len(df),
        train_rows=len(x_train),
        test_rows=len(x_test),
        best_threshold=active_th,
        best_f1=best_f1,
        best_precision=best_p,
        best_recall=best_r,
        roc_auc=float(roc),
        pr_auc=float(pr),
        report=report,
        label_counts=label_counts,
        sources=sources,
        threshold_updated=threshold_updated,
        model_updated=model_updated,
        previous_best_f1=previous_best_f1,
        previous_rows=previous_rows,
        previous_threshold=previous_threshold,
        backtest_summary=backtest_summary,
    )
