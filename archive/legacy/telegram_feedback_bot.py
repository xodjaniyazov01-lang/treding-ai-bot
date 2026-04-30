from __future__ import annotations
import json
import time
import sqlite3
from pathlib import Path
from typing import Tuple, Dict, Any
import requests
from ..config.settings import BOT_TOKEN, CHAT_ID
BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
ROOT = Path(__file__).resolve().parents[3]
OFFSET_FILE = ROOT / ".tg_offset"
DB_PATH = ROOT / "data" / "learn.db"
MODEL_PATH = ROOT / "model.joblib"
THRESH_PATH = ROOT / "threshold.txt"
# ? queue file (ko?p pending)
PENDING_STORE = ROOT / "data" / "pending_signals.json"
PENDING_TTL_SEC = 7 * 24 * 3600  # 7 kun
MAX_PENDING = 200
def api(method: str) -> str:
    return f"{BASE}/{method}"
def ensure_files():
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    if not OFFSET_FILE.exists():
        OFFSET_FILE.write_text("0", encoding="utf-8")
    if not PENDING_STORE.exists():
        PENDING_STORE.write_text("{}", encoding="utf-8")
def _load_pending_store() -> Dict[str, Any]:
    if not PENDING_STORE.exists():
        return {}
    try:
        obj = json.loads(PENDING_STORE.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    # eski format bo?lsa: {"id": "...", "data": {...}}
    if isinstance(obj, dict) and "id" in obj and "data" in obj and isinstance(obj.get("data"), dict):
        sid = str(obj.get("id") or "")
        if sid:
            return {sid: obj["data"]}
        return {}
    return obj if isinstance(obj, dict) else {}
def _save_pending_store(store: Dict[str, Any]) -> None:
    PENDING_STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PENDING_STORE.with_suffix(PENDING_STORE.suffix + ".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PENDING_STORE)
def _prune_pending(store: Dict[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    keep: Dict[str, Any] = {}
    for sid, d in store.items():
        try:
            ts = int((d or {}).get("ts", 0))
        except Exception:
            ts = 0
        if ts and (now - ts) > PENDING_TTL_SEC:
            continue
        keep[sid] = d
    if len(keep) > MAX_PENDING:
        items = list(keep.items())
        items.sort(key=lambda kv: int((kv[1] or {}).get("ts", 0)))
        items = items[-MAX_PENDING:]
        keep = dict(items)
    return keep
def answer_callback(callback_id: str, text: str):
    requests.post(api("answerCallbackQuery"), data={"callback_query_id": callback_id, "text": text}, timeout=20)
def edit_message(chat_id: str, message_id: int, new_text: str):
    requests.post(
        api("editMessageText"),
        data={"chat_id": chat_id, "message_id": message_id, "text": new_text, "disable_web_page_preview": True},
        timeout=20,
    )
def send_msg(text: str):
    requests.post(api("sendMessage"), data={"chat_id": CHAT_ID, "text": text}, timeout=20)
def db_conn():
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
    return con
def insert_labeled(signal_id: str, d: dict, label: int) -> None:
    con = db_conn()
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
def train_from_db() -> Tuple[bool, str]:
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.compose import ColumnTransformer
    from sklearn.preprocessing import OneHotEncoder
    from sklearn.metrics import classification_report, roc_auc_score, average_precision_score, precision_recall_curve
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    con = db_conn()
    try:
        rows = con.execute("SELECT sample_json, label FROM labeled_samples").fetchall()
    finally:
        con.close()
    data = []
    for sample_json, label in rows:
        try:
            sample = json.loads(sample_json) if sample_json else None
        except Exception:
            sample = None
        if not isinstance(sample, dict):
            continue
        s = dict(sample)
        s["label"] = int(label)
        data.append(s)
    # ? minimum 10 (siz oldin o?zgartirgansiz, shu holat qoladi)
    if len(data) < 10:
        return False, f"Data kam: {len(data)} ta (kamida 10 ta WIN/LOSS kerak)"
    df = pd.DataFrame(data)
    df["label"] = pd.to_numeric(df["label"], errors="coerce")
    df = df.dropna(subset=["label"]).copy()
    df["label"] = df["label"].astype(int)
    counts = df["label"].value_counts().to_dict()
    if len(counts) < 2:
        return False, f"Label faqat bitta: {counts} (WIN va LOSS ikkalasi kerak)"
    X = df.drop(columns=["label"]).copy()
    y = df["label"].copy()
    cat_cols = [c for c in X.columns if X[c].dtype == "object"]
    num_cols = [c for c in X.columns if c not in cat_cols]
    for c in cat_cols:
        X[c] = X[c].fillna("NA").astype(str)
    for c in num_cols:
        X[c] = pd.to_numeric(X[c], errors="coerce").fillna(0)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.30, random_state=42, stratify=y
    )
    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), cat_cols),
            ("num", "passthrough", num_cols),
        ]
    )
    use_hgb = len(df) >= 250
    if use_hgb:
        clf = HistGradientBoostingClassifier(max_depth=6, learning_rate=0.06, max_iter=250)
    else:
        clf = LogisticRegression(max_iter=900, class_weight="balanced")
    model = Pipeline([("pre", pre), ("clf", clf)])
    if use_hgb:
        c0 = counts.get(0, 1)
        c1 = counts.get(1, 1)
        w0 = len(y_train) / (2 * c0)
        w1 = len(y_train) / (2 * c1)
        sw = y_train.map(lambda v: w1 if v == 1 else w0).values
        model.fit(X_train, y_train, clf__sample_weight=sw)
    else:
        model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]
    precisions, recalls, thresholds = precision_recall_curve(y_test.values, proba)
    thresholds = np.append(thresholds, 1.0)
    f1 = (2 * precisions * recalls) / (precisions + recalls + 1e-9)
    best_i = int(np.argmax(f1))
    best_th = float(thresholds[best_i])
    preds = (proba >= best_th).astype(int)
    roc = roc_auc_score(y_test, proba)
    pr = average_precision_score(y_test, proba)
    joblib.dump(model, MODEL_PATH)
    THRESH_PATH.write_text(str(best_th), encoding="utf-8")
    rep = classification_report(y_test, preds, digits=2)
    msg = (
        f"? TRAIN DONE (TECH+FUND)\n"
        f"rows={len(df)} labels={counts}\n"
        f"model={'HGB' if use_hgb else 'LogReg'}\n"
        f"threshold={best_th:.3f} | ROC_AUC={roc:.3f} | PR_AUC={pr:.3f}\n\n"
        f"{rep}"
    )
    return True, msg
def poll():
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: BOT_TOKEN yoki CHAT_ID yo?q. .env tekshir.")
        return
    ensure_files()
    print("?? FEEDBACK BOT started (SQL + Auto-train + QUEUE). Stop: CTRL+C")
    try:
        offset = int(OFFSET_FILE.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        offset = 0
    while True:
        try:
            r = requests.get(api("getUpdates"), params={"timeout": 30, "offset": offset}, timeout=40)
            data = r.json()
            if not data.get("ok"):
                time.sleep(2)
                continue
            for upd in data["result"]:
                offset = upd["update_id"] + 1
                OFFSET_FILE.write_text(str(offset), encoding="utf-8")
                cq = upd.get("callback_query")
                if not cq:
                    continue
                cb_id = cq["id"]
                msg = cq.get("message", {})
                chat = msg.get("chat", {})
                chat_id = str(chat.get("id", ""))
                if chat_id != str(CHAT_ID):
                    answer_callback(cb_id, "Not allowed")
                    continue
                callback_data = cq.get("data", "")
                if ":" not in callback_data:
                    answer_callback(cb_id, "Bad callback")
                    continue
                action, signal_id = callback_data.split(":", 1)
                action = action.strip().upper()
                if action not in ("WIN", "LOSS"):
                    answer_callback(cb_id, "Unknown action")
                    continue
                store = _load_pending_store()
                store = _prune_pending(store)
                d = store.get(signal_id)
                if not isinstance(d, dict):
                    _save_pending_store(store)
                    answer_callback(cb_id, "Pending signal topilmadi yoki eskirgan")
                    continue
                label = 1 if action == "WIN" else 0
                insert_labeled(signal_id, d, label)
                # ? queue?dan o?chiramiz (faqat 1 marta bosiladi)
                del store[signal_id]
                _save_pending_store(store)
                # message update
                message_id = msg.get("message_id")
                try:
                    old_text = msg.get("text", "")
                    new_text = old_text + f"\n\nRESULT: {action}"
                    if message_id is not None:
                        edit_message(chat_id, message_id, new_text)
                except Exception:
                    pass
                answer_callback(cb_id, f"Saved: {action}")
                ok, report = train_from_db()
                if ok:
                    send_msg(report[:3500])
                else:
                    send_msg(f"? Saved {action} (SQL). TRAIN: {report}")
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except Exception as e:
            print("error:", e)
            time.sleep(2)
if __name__ == "__main__":
    poll()
