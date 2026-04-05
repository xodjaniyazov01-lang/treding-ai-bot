from __future__ import annotations
import argparse, json, sqlite3, time
from pathlib import Path
from datetime import datetime
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODEL = ROOT / "model.joblib"
THRESH = ROOT / "threshold.txt"
DB = DATA / "learn.db"
PENDING = DATA / "pending_signals.json"
STATE = DATA / "last_best_signal.json"
TG_OFFSET = ROOT / ".tg_offset"
def fmt_ts(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "N/A"
def file_info(p: Path) -> str:
    if not p.exists():
        return f"{p.name}: MISSING"
    st = p.stat()
    return f"{p.name}: ok | size={st.st_size} | mtime={fmt_ts(st.st_mtime)}"
def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""
def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
def db_stats():
    if not DB.exists():
        return {"rows": 0, "win": 0, "loss": 0, "last": []}
    con = sqlite3.connect(DB)
    try:
        con.execute("""
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
        """)
        con.commit()
        rows = con.execute("SELECT COUNT(*) FROM labeled_samples").fetchone()[0] or 0
        win = con.execute("SELECT COUNT(*) FROM labeled_samples WHERE label=1").fetchone()[0] or 0
        loss = con.execute("SELECT COUNT(*) FROM labeled_samples WHERE label=0").fetchone()[0] or 0
        last = con.execute("""
            SELECT ts, ticker, tf, signal, p, side, label
            FROM labeled_samples
            ORDER BY ts DESC
            LIMIT 5
        """).fetchall()
        return {"rows": rows, "win": win, "loss": loss, "last": last}
    finally:
        con.close()
def pending_stats():
    obj = load_json(PENDING)
    if not isinstance(obj, dict):
        return {"count": 0, "newest": None, "oldest": None}
    if len(obj) == 0:
        return {"count": 0, "newest": None, "oldest": None}
    ts_list = []
    for _, d in obj.items():
        if isinstance(d, dict) and "ts" in d:
            try:
                ts_list.append(int(d["ts"]))
            except Exception:
                pass
    newest = max(ts_list) if ts_list else None
    oldest = min(ts_list) if ts_list else None
    return {"count": len(obj), "newest": newest, "oldest": oldest}
def show_once():
    print("="*60)
    print("TIME:", fmt_ts(time.time()))
    print("-"*60)
    # Model / threshold
    print(file_info(MODEL))
    th = read_text(THRESH)
    print("threshold.txt:", th if th else "N/A")
    # Pending queue
    print(file_info(PENDING))
    ps = pending_stats()
    print(f"pending count: {ps['count']}")
    if ps["oldest"]:
        print("pending oldest:", fmt_ts(ps["oldest"]))
    if ps["newest"]:
        print("pending newest:", fmt_ts(ps["newest"]))
    # Last best signal state
    print(file_info(STATE))
    st = load_json(STATE)
    if isinstance(st, dict):
        print("last_best_signal.json:", st)
    # Feedback bot heartbeat (offset file)
    print(file_info(TG_OFFSET))
    off = read_text(TG_OFFSET)
    if off:
        print(".tg_offset:", off)
    # DB stats
    ds = db_stats()
    print("-"*60)
    print(f"learn.db rows={ds['rows']} | WIN={ds['win']} | LOSS={ds['loss']}")
    if ds["last"]:
        print("last 5 labels:")
        for ts, ticker, tf, signal, p, side, label in ds["last"]:
            print(f"  {fmt_ts(ts)} | {ticker} {tf} | {signal} p={p:.2f} | {side} | label={'WIN' if label==1 else 'LOSS'}")
    print("="*60)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="har 5 sekundda yangilab turadi")
    ap.add_argument("--sec", type=int, default=5)
    args = ap.parse_args()
    if not args.watch:
        show_once()
        return
    while True:
        show_once()
        time.sleep(max(1, args.sec))
if __name__ == "__main__":
    main()
