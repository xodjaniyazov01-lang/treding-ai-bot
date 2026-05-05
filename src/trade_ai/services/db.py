from __future__ import annotations

import sqlite3
import time
from typing import Optional, Tuple

from trade_ai.config import settings
from trade_ai.core.data_loader import yf_download_safe


def db_connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(settings.SIGNALS_DB_PATH))
    con.execute("PRAGMA journal_mode=WAL;")
    return con


def init_db() -> None:
    con = db_connect()
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                ts INTEGER,
                ticker TEXT,
                side TEXT,
                tf_label TEXT,
                interval TEXT,
                p REAL,
                entry REAL,
                sl REAL,
                tp REAL,
                status TEXT,
                outcome TEXT,
                close_ts INTEGER,
                close_price REAL
            );
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                k TEXT PRIMARY KEY,
                v TEXT
            );
            """
        )
        ensure_signal_schema(con)
        con.commit()
    finally:
        con.close()


def ensure_signal_schema(con: sqlite3.Connection) -> None:
    existing = {
        str(row[1]).lower()
        for row in con.execute("PRAGMA table_info(signals);").fetchall()
    }
    required_columns = {
        "price_at_signal": "REAL",
        "price_at_check": "REAL",
        "pnl_pct": "REAL",
        "validated_at": "TEXT",
        "validation_outcome": "TEXT",
    }
    for column, col_type in required_columns.items():
        if column not in existing:
            con.execute(f"ALTER TABLE signals ADD COLUMN {column} {col_type};")

    con.execute(
        """
        UPDATE signals
        SET price_at_signal = entry
        WHERE price_at_signal IS NULL
          AND entry IS NOT NULL;
        """
    )
    con.execute(
        """
        UPDATE signals
        SET validation_outcome='PENDING'
        WHERE status='OPEN'
          AND validated_at IS NULL
          AND (validation_outcome IS NULL OR validation_outcome = '');
        """
    )


def set_meta(key: str, value: str) -> None:
    con = db_connect()
    try:
        con.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v;", (key, value))
        con.commit()
    finally:
        con.close()


def get_meta(key: str, default: str = "") -> str:
    con = db_connect()
    try:
        row = con.execute("SELECT v FROM meta WHERE k=?;", (key,)).fetchone()
        return row[0] if row and row[0] is not None else default
    finally:
        con.close()


def insert_signal(
    sig_id: str,
    ts: int,
    ticker: str,
    side: str,
    tf_label: str,
    interval: str,
    p: float,
    entry: float,
    sl: float,
    tp: float,
    price_at_signal: Optional[float] = None,
) -> None:
    con = db_connect()
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO signals(
                id,ts,ticker,side,tf_label,interval,p,entry,sl,tp,
                status,outcome,close_ts,close_price,
                price_at_signal,price_at_check,pnl_pct,validated_at,validation_outcome
            )
            VALUES(?,?,?,?,?,?,?,?,?,?, 'OPEN', 'UNKNOWN', NULL, NULL, ?, NULL, NULL, NULL, 'PENDING');
            """,
            (sig_id, ts, ticker, side, tf_label, interval, p, entry, sl, tp, price_at_signal),
        )
        con.commit()
    finally:
        con.close()


def close_signal(sig_id: str, outcome: str, close_ts: int, close_price: float) -> None:
    con = db_connect()
    try:
        con.execute(
            """
            UPDATE signals
            SET status='CLOSED', outcome=?, close_ts=?, close_price=?
            WHERE id=?;
            """,
            (outcome, close_ts, close_price, sig_id),
        )
        con.commit()
    finally:
        con.close()


def get_open_signals(limit: int = 50):
    con = db_connect()
    try:
        cur = con.execute(
            """
            SELECT id, ts, ticker, side, interval, entry, sl, tp
            FROM signals
            WHERE status='OPEN'
            ORDER BY ts ASC
            LIMIT ?;
            """,
            (limit,),
        )
        return cur.fetchall()
    finally:
        con.close()


def win_rate_ticker(ticker: str, n: int = 10) -> Tuple[int, int]:
    con = db_connect()
    try:
        rows = con.execute(
            """
            SELECT outcome
            FROM signals
            WHERE status='CLOSED' AND ticker=?
            ORDER BY close_ts DESC
            LIMIT ?;
            """,
            (ticker, n),
        ).fetchall()
    finally:
        con.close()
    outcomes = [row[0] for row in rows]
    total = sum(1 for outcome in outcomes if outcome in ("TP", "SL", "AMBIGUOUS"))
    wins = sum(1 for outcome in outcomes if outcome == "TP")
    return wins, total


def win_rate_global(n: int = 30) -> Tuple[int, int]:
    con = db_connect()
    try:
        rows = con.execute(
            """
            SELECT outcome
            FROM signals
            WHERE status='CLOSED'
            ORDER BY close_ts DESC
            LIMIT ?;
            """,
            (n,),
        ).fetchall()
    finally:
        con.close()
    outcomes = [row[0] for row in rows]
    total = sum(1 for outcome in outcomes if outcome in ("TP", "SL", "AMBIGUOUS"))
    wins = sum(1 for outcome in outcomes if outcome == "TP")
    return wins, total


def stats_summary() -> Tuple[int, int, int]:
    con = db_connect()
    try:
        total_signals = int(con.execute("SELECT COUNT(*) FROM signals;").fetchone()[0] or 0)
        rows = con.execute("SELECT outcome FROM signals WHERE status='CLOSED';").fetchall()
    finally:
        con.close()
    outcomes = [row[0] for row in rows]
    total_closed = sum(1 for outcome in outcomes if outcome in ("TP", "SL", "AMBIGUOUS"))
    wins = sum(1 for outcome in outcomes if outcome == "TP")
    return total_signals, wins, total_closed


def decide_outcome(side: str, sl: float, tp: float, df) -> Optional[Tuple[str, int, float]]:
    if df is None or getattr(df, "empty", False):
        return None
    if not all(col in df.columns for col in ("High", "Low", "Close")):
        return None
    side = (side or "").upper()
    for _, row in df.iterrows():
        try:
            high = float(row["High"])
            low = float(row["Low"])
        except Exception:
            continue
        if side == "BUY":
            hit_sl = low <= sl
            hit_tp = high >= tp
        else:
            hit_sl = high >= sl
            hit_tp = low <= tp
        if hit_sl and hit_tp:
            return "AMBIGUOUS", int(time.time()), float(sl)
        if hit_sl:
            return "SL", int(time.time()), float(sl)
        if hit_tp:
            return "TP", int(time.time()), float(tp)
    return None


def update_open_signal_outcomes(limit: int = 50) -> None:
    for sig_id, _ts, ticker, side, interval, _entry, sl, tp in get_open_signals(limit=limit):
        try:
            df = yf_download_safe(ticker, period="7d", interval=interval, min_rows=10, retries=2)
            outcome = decide_outcome(side, float(sl), float(tp), df)
            if outcome:
                close_signal(sig_id, outcome[0], outcome[1], outcome[2])
        except Exception:
            continue
