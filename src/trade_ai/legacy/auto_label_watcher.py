from __future__ import annotations
import json
import time
import sqlite3
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
try:
    import yfinance as yf
except Exception:
    yf = None
ROOT = Path(__file__).resolve().parents[3]
PENDING_STORE = ROOT / "data" / "pending_signals.json"
DB_PATH = ROOT / "data" / "learn.db"
POLL_SEC = 60            # har 60 sekund tekshiradi
LOOKBACK_PERIOD = "2d"   # data olish (yfinance)
INTERVAL = "5m"          # sizda TF=M5
def _load_store() -> Dict[str, Any]:
    if not PENDING_STORE.exists():
        return {}
    try:
        obj = json.loads(PENDING_STORE.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}
def _save_store(store: Dict[str, Any]) -> None:
    PENDING_STORE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_STORE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
def _ensure_db():
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS labeled_samples (
            id TEXT PRIMARY KEY,
            ts INTEGER,
            ticker TEXT,
            tf TEXT,
            signal TEXT,
            p REAL,
            side TEXT,
            label INTEGER,
            sample_json TEXT
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_labeled_ts ON labeled_samples(ts)")
    con.commit()
    con.close()
def _insert_labeled(signal_id: str, d: dict, label: int) -> None:
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO labeled_samples
            (id, ts, ticker, tf, signal, p, side, label, sample_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id,
                int(time.time()),
                str(d.get("ticker", "")),
                str(d.get("tf", "")),
                str(d.get("signal", "")),
                float(d.get("p", 0.0)),
                str(d.get("side", "")),
                int(label),
                json.dumps(d.get("sample", None), ensure_ascii=False),
            ),
        )
        con.commit()
    finally:
        con.close()
def _fetch_m5(ticker: str):
    if yf is None:
        return None
    try:
        df = yf.download(
            ticker,
            period=LOOKBACK_PERIOD,
            interval=INTERVAL,
            auto_adjust=False,
            progress=False,
            group_by="column",
        )
    except Exception:
        return None
    if df is None or len(df) < 10:
        return None
    # MultiIndex bo‘lsa tekislaymiz
    try:
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = [c[0] for c in df.columns]
    except Exception:
        pass
    need = {"High", "Low", "Close"}
    if not need.issubset(set(df.columns)):
        return None
    df = df.dropna().copy()
    return df
def _ts_from_pending(d: dict) -> int:
    # signal yaratilgan vaqt (epoch)
    try:
        return int(d.get("ts", 0))
    except Exception:
        return 0
def _decide_hit(df, d: dict) -> Tuple[Optional[int], str]:
    """
    Returns: (label, reason)
      label: 1=WIN, 0=LOSS, None=not decided yet
    """
    side = str(d.get("side", "")).upper()
    entry = d.get("entry", None)
    sl = d.get("sl", None)
    tp = d.get("tp", None)
    if entry is None or sl is None or tp is None:
        return None, "no_entry_sl_tp"
    try:
        entry = float(entry); sl = float(sl); tp = float(tp)
    except Exception:
        return None, "bad_numbers"
    sig_ts = _ts_from_pending(d)
    if sig_ts <= 0:
        return None, "no_ts"
    # yfinance index: datetime; biz epoch bilan solishtirish uchun timestamp olamiz
    # df.index tz bo‘lishi mumkin, shuning uchun safe conversion:
    try:
        idx_ts = df.index.astype("int64") // 10**9
    except Exception:
        # fallback
        idx_ts = [int(x.timestamp()) for x in df.index.to_pydatetime()]
    highs = df["High"].values
    lows = df["Low"].values
    # signal vaqtidan keyingi candle’larni ko‘ramiz
    # (>= sig_ts bo‘lsa ham bo‘ladi, lekin konservativ: keyingi candle’dan)
    started = False
    for i in range(len(df)):
        t = int(idx_ts[i])
        if not started:
            if t >= sig_ts:
                started = True
            else:
                continue
        hi = float(highs[i])
        lo = float(lows[i])
        # BUY: TP hit => hi >= tp; SL hit => lo <= sl
        # SELL: TP hit => lo <= tp; SL hit => hi >= sl
        if side == "BUY":
            hit_tp = hi >= tp
            hit_sl = lo <= sl
        else:  # SELL
            hit_tp = lo <= tp
            hit_sl = hi >= sl
        # Agar bitta candle ichida ikkalasi ham bo‘lsa — konservativ LOSS
        if hit_tp and hit_sl:
            return 0, "both_hit_same_candle"
        if hit_sl:
            return 0, "sl_first"
        if hit_tp:
            return 1, "tp_first"
    return None, "not_yet"
def _try_train() -> Tuple[bool, str]:
    # feedback botdagi train_from_db ni ishlatamiz
    try:
        from trade_ai.legacy.telegram_feedback_bot import train_from_db
        ok, msg = train_from_db()
        return ok, msg
    except Exception as e:
        return False, f"train_error: {e!r}"
def main():
    _ensure_db()
    PENDING_STORE.parent.mkdir(parents=True, exist_ok=True)
    if not PENDING_STORE.exists():
        PENDING_STORE.write_text("{}", encoding="utf-8")
    print("🟢 AUTO-LABEL WATCHER started (M5). Stop: CTRL+C")
    while True:
        try:
            store = _load_store()
            if not store:
                time.sleep(POLL_SEC)
                continue
            changed = False
            # copy keys list to modify store safely
            for signal_id in list(store.keys()):
                d = store.get(signal_id)
                if not isinstance(d, dict):
                    del store[signal_id]
                    changed = True
                    continue
                ticker = str(d.get("ticker", "")).upper().strip()
                if not ticker:
                    del store[signal_id]
                    changed = True
                    continue
                df = _fetch_m5(ticker)
                if df is None:
                    continue
                label, reason = _decide_hit(df, d)
                if label is None:
                    continue
                # ✅ label saqlaymiz va queue’dan o‘chiramiz
                _insert_labeled(signal_id, d, int(label))
                del store[signal_id]
                changed = True
                print(f"✅ AUTO LABELED: {ticker} id={signal_id} -> {'WIN' if label==1 else 'LOSS'} ({reason})")
                # har labeldan keyin train urinish (data yetarli bo‘lmasa o‘zi aytadi)
                ok, report = _try_train()
                if ok:
                    print("✅ TRAIN DONE (auto)")
                else:
                    # data kam bo‘lsa ham normal
                    pass
            if changed:
                _save_store(store)
            time.sleep(POLL_SEC)
        except KeyboardInterrupt:
            print("\n🛑 stopped.")
            break
        except Exception as e:
            print("⚠️ error:", repr(e))
            time.sleep(3)
if __name__ == "__main__":
    main()
