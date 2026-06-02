from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from trade_ai.config import settings
from trade_ai.core.data_loader import yf_download_safe

CHECK_AFTER_SECONDS = 60 * 60

logger = logging.getLogger("trade_ai.validator")


def _latest_price(ticker: str) -> Optional[float]:
    df = yf_download_safe(ticker, period="1d", interval="1m", min_rows=1, retries=2)
    if df is None or getattr(df, "empty", False) or "Close" not in df.columns:
        return None
    try:
        price = float(df["Close"].iloc[-1])
    except Exception:
        return None
    return price if price > 0 else None


def validate_pending(db_path: str | Path | None = None) -> List[Dict[str, Any]]:
    path = Path(db_path) if db_path is not None else settings.SIGNALS_DB_PATH
    now_ts = int(time.time())
    cutoff_ts = now_ts - CHECK_AFTER_SECONDS
    now_iso = datetime.utcnow().isoformat()

    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000;")
    try:
        rows = conn.execute(
            """
            SELECT id, ticker, side, p, ts, entry, price_at_signal
            FROM signals
            WHERE validated_at IS NULL
              AND validation_outcome='PENDING'
              AND ts <= ?
            ORDER BY ts ASC;
            """,
            (cutoff_ts,),
        ).fetchall()

        results: List[Dict[str, Any]] = []
        for signal_id, ticker, side, p, ts, entry, price_at_signal in rows:
            price_open = float(price_at_signal or entry or 0.0)
            if price_open <= 0:
                logger.warning("Validator skipped %s: missing open price", signal_id)
                continue

            price_now = _latest_price(str(ticker))
            if price_now is None:
                logger.warning("Validator skipped %s: missing latest price for %s", signal_id, ticker)
                continue

            side_upper = str(side or "").upper()
            if "BUY" in side_upper:
                pnl_pct = ((price_now - price_open) / price_open) * 100.0
            elif "SELL" in side_upper:
                pnl_pct = ((price_open - price_now) / price_open) * 100.0
            else:
                logger.warning("Validator skipped %s: unsupported side %s", signal_id, side)
                continue
            validation_outcome = "WIN" if pnl_pct > 0 else "LOSS"

            conn.execute(
                """
                UPDATE signals
                SET price_at_check=?,
                    pnl_pct=?,
                    validated_at=?,
                    validation_outcome=?,
                    outcome=?
                WHERE id=?;
                """,
                (
                    price_now,
                    round(pnl_pct, 3),
                    now_iso,
                    validation_outcome,
                    validation_outcome,
                    signal_id,
                ),
            )
            results.append(
                {
                    "id": signal_id,
                    "ticker": ticker,
                    "side": side_upper,
                    "p": float(p or 0.0),
                    "pnl": round(pnl_pct, 3),
                    "outcome": validation_outcome,
                    "price_open": price_open,
                    "price_now": price_now,
                    "signal_ts": int(ts or 0),
                }
            )

        conn.commit()
        return results
    finally:
        conn.close()

