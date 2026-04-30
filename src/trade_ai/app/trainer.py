from __future__ import annotations

from trade_ai.core.model import train_and_save
from trade_ai.utils.logger import setup_logger

logger = setup_logger("trade_ai.trainer")


def main() -> None:
    result = train_and_save()
    logger.info("Training rows=%d train=%d test=%d", result.rows, result.train_rows, result.test_rows)
    logger.info("Label counts=%s", result.label_counts)
    logger.info(
        "Threshold=%.4f F1=%.3f Precision=%.3f Recall=%.3f ROC_AUC=%.3f PR_AUC=%.3f",
        result.best_threshold,
        result.best_f1,
        result.best_precision,
        result.best_recall,
        result.roc_auc,
        result.pr_auc,
    )
    logger.info("Classification report:\n%s", result.report)


if __name__ == "__main__":
    main()
