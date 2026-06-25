from __future__ import annotations

from trade_ai.core.model import train_and_save
from trade_ai.utils.logger import setup_logger

logger = setup_logger("trade_ai.trainer")


def main() -> None:
    result = train_and_save()
    logger.info("Training rows=%d train=%d test=%d", result.rows, result.train_rows, result.test_rows)
    logger.info("Training sources=%s", result.sources)
    logger.info("Signal history=%s", result.backtest_summary)
    logger.info("Label counts=%s", result.label_counts)
    logger.info(
        "Threshold=%.4f updated=%s model_updated=%s previous_f1=%s F1=%.3f Precision=%.3f Recall=%.3f ROC_AUC=%.3f PR_AUC=%.3f",
        result.best_threshold,
        result.threshold_updated,
        result.model_updated,
        f"{result.previous_best_f1:.3f}" if result.previous_best_f1 is not None else "None",
        result.best_f1,
        result.best_precision,
        result.best_recall,
        result.roc_auc,
        result.pr_auc,
    )
    logger.info("Classification report:\n%s", result.report)


if __name__ == "__main__":
    main()
