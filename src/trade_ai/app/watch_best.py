from __future__ import annotations
import re
import json
import time
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from datetime import datetime
import requests
import contextlib
import io
from trade_ai.config.settings import BOT_TOKEN, CHAT_ID
from trade_ai.legacy.telegram_alert import send_signal_card
try:
    import yfinance as yf
except Exception:
    yf = None
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = ROOT / "signals_history.db"  # talab: signals_history.db
STATE_FILE = DATA_DIR / "watch_state.json"
THRESH_PATH = ROOT / "threshold.txt"
WATCHLIST = ROOT / "watchlist.txt"
SLEEP_SEC = 300  # auto loop: M5=300s, M15=900s
DUPLICATE_TTL_SEC = 300
TF_LABEL = "M5"   # runtime’da o'zgaradi
TF_INTERVAL = "5m"
TF_MAP = {
    "M5":  ("5m",  "10d"),
    "M15": ("15m", "30d"),
    "H1":  ("60m", "180d"),
    "H4":  ("60m", "180d"),  # 4h interval yo‘q; 60m ishlatamiz
}
def sleep_sec_for_tf(tf_label: str) -> int:
    tf = (tf_label or "").upper()
    if tf == "M5":
        return 300
    if tf == "M15":
        return 900
    if tf == "H1":
        return 3600
    if tf == "H4":
        return 14400
    return 300

# Stats
TOTAL_SCANS = 0
DATA_ERRORS = 0
LOW_PROBA_SKIPS = 0
SIGNALS_SENT = 0
# Session management
sent_signals: set[str] = set()
LINE_RE = re.compile(r"^\s*(?P<ticker>[A-Z0-9\.\-]+)\s*:\s*(?P<signal>[A-Z_]+)\s*\((?P<body>.*)\)\s*$", re.IGNORECASE)
@dataclass
class Pick:
    ticker: str
    signal: str
    p: float
    side: str
    threshold: Optional[float] = None
    reason: Optional[str] = None
    err: Optional[str] = None
    entry: Optional[float] = None
    atr: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    squeeze: Optional[str] = None
    breakout: Optional[str] = None
    h1: Optional[str] = None
    d1: Optional[str] = None
# ---------------- Telegram helpers ----------------
def tg_api(method: str, data: dict) -> Tuple[int, str]:
    if not BOT_TOKEN:
        return 0, "missing BOT_TOKEN"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=data, timeout=12)
        return r.status_code, r.text[:500]
    except Exception as e:
        return 0, repr(e)
def tg_send_text(text: str, reply_markup: Optional[dict] = None) -> Tuple[int, str]:
    payload = {"chat_id": CHAT_ID, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return tg_api("sendMessage", payload)
def tg_answer_callback(callback_query_id: str, text: str = "") -> Tuple[int, str]:
    return tg_api("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})
def tf_keyboard() -> dict:
    # InlineKeyboardMarkup JSON
    return {
        "inline_keyboard": [
            [{"text": "M5", "callback_data": "TF:M5"},
             {"text": "M15", "callback_data": "TF:M15"},
             {"text": "H1", "callback_data": "TF:H1"},
             {"text": "H4", "callback_data": "TF:H4"}],
        ]
    }
# --------------------------------------------------
# ---------------- Persistence ----------------
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}
    return {}
def save_state(st: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
# --------------------------------------------
# ---------------- SQLite (Feedback loop DB) ----------------
def db_connect():
    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA journal_mode=WAL;")
    return con
def db_init():
    con = db_connect()
    con.execute("""
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
        status TEXT,        -- OPEN/CLOSED
        outcome TEXT,       -- TP/SL/AMBIGUOUS/UNKNOWN
        close_ts INTEGER,
        close_price REAL
    );
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS meta (
        k TEXT PRIMARY KEY,
        v TEXT
    );
    """)
    con.commit()
    con.close()
def db_set_meta(k: str, v: str):
    con = db_connect()
    con.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v;", (k, v))
    con.commit()
    con.close()
def db_get_meta(k: str, default: str = "") -> str:
    con = db_connect()
    cur = con.execute("SELECT v FROM meta WHERE k=?;", (k,))
    row = cur.fetchone()
    con.close()
    return row[0] if row and row[0] is not None else default
def db_insert_signal(sig_id: str, ts: int, ticker: str, side: str, tf_label: str, interval: str, p: float, entry: float, sl: float, tp: float):
    con = db_connect()
    con.execute("""
    INSERT OR REPLACE INTO signals(id,ts,ticker,side,tf_label,interval,p,entry,sl,tp,status,outcome,close_ts,close_price)
    VALUES(?,?,?,?,?,?,?,?,?,?, 'OPEN', 'UNKNOWN', NULL, NULL);
    """, (sig_id, ts, ticker, side, tf_label, interval, p, entry, sl, tp))
    con.commit()
    con.close()
def db_close_signal(sig_id: str, outcome: str, close_ts: int, close_price: float):
    con = db_connect()
    con.execute("""
    UPDATE signals
    SET status='CLOSED', outcome=?, close_ts=?, close_price=?
    WHERE id=?;
    """, (outcome, close_ts, close_price, sig_id))
    con.commit()
    con.close()
def db_get_open_signals(limit: int = 50):
    con = db_connect()
    cur = con.execute("""
    SELECT id, ts, ticker, side, interval, entry, sl, tp
    FROM signals
    WHERE status='OPEN'
    ORDER BY ts ASC
    LIMIT ?;
    """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows
def db_win_rate_ticker(ticker: str, n: int = 10) -> Tuple[int, int]:
    con = db_connect()
    cur = con.execute("""
    SELECT outcome
    FROM signals
    WHERE status='CLOSED' AND ticker=?
    ORDER BY close_ts DESC
    LIMIT ?;
    """, (ticker, n))
    outs = [r[0] for r in cur.fetchall()]
    con.close()
    total = sum(1 for o in outs if o in ("TP", "SL", "AMBIGUOUS"))
    wins = sum(1 for o in outs if o == "TP")
    return wins, total
def db_win_rate_global(n: int = 30) -> Tuple[int, int]:
    con = db_connect()
    cur = con.execute("""
    SELECT outcome
    FROM signals
    WHERE status='CLOSED'
    ORDER BY close_ts DESC
    LIMIT ?;
    """, (n,))
    outs = [r[0] for r in cur.fetchall()]
    con.close()
    total = sum(1 for o in outs if o in ("TP", "SL", "AMBIGUOUS"))
    wins = sum(1 for o in outs if o == "TP")
    return wins, total
# ---------------------------------------------------------
# ---------------- yfinance safe download (silence + retry) ----------------
def yf_download_safe(ticker: str, period: str, interval: str, min_rows: int = 60, retries: int = 3):
    if yf is None:
        return None
    last_df = None
    for i in range(max(1, retries)):
        try:
            buf_out, buf_err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                df = yf.download(
                    ticker,
                    period=period,
                    interval=interval,
                    progress=False,
                    threads=False,
                    timeout=5,
                    auto_adjust=False,
                    group_by="column",
                )
        except Exception:
            df = None
        if df is not None and not getattr(df, "empty", False) and len(df) >= min_rows:
            try:
                if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                    df.columns = [c[0] for c in df.columns]
            except Exception:
                pass
            return df
        last_df = df
        time.sleep(1.0 * (2 ** i))
    return last_df
# -------------------------------------------------------------------------
def rsi14_from_close(close) -> Optional[float]:
    try:
        s = close.astype(float)
        delta = s.diff()
        up = delta.clip(lower=0).rolling(14).mean()
        down = (-delta.clip(upper=0)).rolling(14).mean()
        rs = up / (down + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        v = float(rsi.iloc[-1])
        if v == v:
            return v
    except Exception:
        pass
    return None
def fetch_entry_atr_rsi(ticker: str, interval: str, period: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    df = yf_download_safe(ticker, period=period, interval=interval, min_rows=60, retries=3)
    if df is None or getattr(df, "empty", False) or len(df) < 60:
        return None, None, None
    for col in ("High", "Low", "Close"):
        if col not in df.columns:
            return None, None, None
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = tr1.combine(tr2, max).combine(tr3, max)
    atr = true_range.rolling(14).mean()
    entry = float(close.iloc[-1])
    atr14 = float(atr.iloc[-1]) if atr.iloc[-1] == atr.iloc[-1] else None
    rsi_v = rsi14_from_close(close)
    return entry, atr14, rsi_v
def calc_sl_tp(entry: float, atr14: float, side: str) -> Tuple[float, float]:
    sl_dist = 2.0 * atr14
    tp_dist = 3.0 * atr14
    side = side.upper()
    if side == "BUY":
        return entry - sl_dist, entry + tp_dist
    return entry + sl_dist, entry - tp_dist
def sltp_valid(entry: float, sl: float, tp: float, side: str) -> bool:
    side = side.upper()
    if side == "BUY":
        return sl < entry < tp
    if side == "SELL":
        return tp < entry < sl
    return False
def run_multi_predict(tf_label: str) -> str:
    cmd = [sys.executable, "-m", "trade_ai.legacy.multi_predict", "--auto", "--tf", tf_label]
    return subprocess.check_output(cmd, text=True, errors="ignore", cwd=str(ROOT))
def parse_picks(stdout: str) -> List[Pick]:
    picks: List[Pick] = []
    for line in stdout.splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        ticker = m.group("ticker").upper()
        signal = m.group("signal").upper()
        body = m.group("body")
        kv: Dict[str, str] = {}
        for part in body.split(","):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                kv[k.strip().lower()] = v.strip()
        def _f(x: Optional[str], default: Optional[float] = None) -> Optional[float]:
            try:
                if x is None:
                    return default
                return float(x)
            except Exception:
                return default
        p = _f(kv.get("p"), 0.0) or 0.0
        th = _f(kv.get("th"), None)
        side = (kv.get("side") or "").upper() or ("SELL" if "SELL" in signal else "BUY")
        reason = kv.get("reason")
        err = kv.get("err")
        entry = _f(kv.get("entry"), None)
        atr   = _f(kv.get("atr"), None)
        sl    = _f(kv.get("sl"), None)
        tp    = _f(kv.get("tp"), None)
        squeeze = kv.get("squeeze")
        breakout = kv.get("breakout")
        h1 = kv.get("h1")
        d1 = kv.get("d1")
        picks.append(Pick(ticker=ticker, signal=signal, p=p, side=side, threshold=th, reason=reason, err=err, entry=entry, atr=atr, sl=sl, tp=tp, squeeze=squeeze, breakout=breakout, h1=h1, d1=d1))
    return picks

def pick_best(picks: List[Pick]) -> Optional[Pick]:
    cands = []
    for x in picks:
        u = (x.signal or "").upper()
        if "HOLD" in u or "CONFLICT" in u:
            continue
        if ("BUY" in u) or ("SELL" in u):
            cands.append(x)
    if not cands:
        return None
    def score(z: Pick) -> float:
        s = (z.signal or "").upper()
        base = float(z.p or 0.0)
        # EXPLOSIVE highest priority
        if "EXPLOSIVE" in s:
            base += 10.0
        # STRONG slightly higher than normal
        if s.startswith("STRONG_") or "STRONG_" in s:
            base += 0.5
        return base
    cands.sort(key=score, reverse=True)
    return cands[0]

def decide_outcome(side: str, entry: float, sl: float, tp: float, df) -> Optional[Tuple[str, int, float]]:
    """
    df: OHLCV time series AFTER signal time. Returns (outcome, close_ts, close_price)
    """
    side = side.upper()
    if df is None or getattr(df, "empty", False):
        return None
    if not all(c in df.columns for c in ("High", "Low", "Close")):
        return None
    # iterate chronological
    for idx, row in df.iterrows():
        hi = float(row["High"])
        lo = float(row["Low"])
        # BUY: SL if lo<=sl, TP if hi>=tp
        if side == "BUY":
            hit_sl = lo <= sl
            hit_tp = hi >= tp
            if hit_sl and hit_tp:
                # ambiguous -> conservative SL
                return ("AMBIGUOUS", int(time.time()), float(sl))
            if hit_sl:
                return ("SL", int(time.time()), float(sl))
            if hit_tp:
                return ("TP", int(time.time()), float(tp))
        else:
            # SELL: SL if hi>=sl, TP if lo<=tp
            hit_sl = hi >= sl
            hit_tp = lo <= tp
            if hit_sl and hit_tp:
                return ("AMBIGUOUS", int(time.time()), float(sl))
            if hit_sl:
                return ("SL", int(time.time()), float(sl))
            if hit_tp:
                return ("TP", int(time.time()), float(tp))
    return None
def outcome_tracker():
    """
    Check OPEN signals and close if TP/SL reached.
    """
    rows = db_get_open_signals(limit=50)
    for sig_id, ts, ticker, side, interval, entry, sl, tp in rows:
        # fetch recent data (7d) and evaluate
        df = yf_download_safe(ticker, period="7d", interval=interval, min_rows=10, retries=2)
        if df is None or getattr(df, "empty", False):
            continue
        out = decide_outcome(side, float(entry), float(sl), float(tp), df)
        if out:
            outcome, close_ts, close_price = out
            db_close_signal(sig_id, outcome, close_ts, close_price)
# ---------------- Self optimization (threshold tuning) ----------------
def read_threshold(default: float = 0.55) -> float:
    try:
        raw = THRESH_PATH.read_text(encoding="utf-8", errors="ignore").replace("\ufeff", "").strip()
        return float(raw)
    except Exception:
        return default
def write_threshold(v: float) -> None:
    v = max(0.20, min(0.85, float(v)))
    try:
        THRESH_PATH.write_text(f"{v:.4f}", encoding="utf-8")
    except Exception:
        pass
def maybe_adjust_threshold():
    """
    Simple policy:
      - look at last 30 closed
      - winrate < 45% => threshold +0.02
      - winrate > 60% => threshold -0.01
      - adjust max once per day
    """
    today = datetime.now().date().isoformat()
    last_adj = db_get_meta("last_adj_date", "")
    if last_adj == today:
        return
    wins, total = db_win_rate_global(n=30)
    if total < 10:
        return
    wr = wins / max(1, total)
    th = read_threshold(default=0.55)
    new_th = th
    if wr < 0.45:
        new_th = th + 0.02
    elif wr > 0.60:
        new_th = th - 0.01
    new_th = max(0.20, min(0.85, new_th))
    if abs(new_th - th) >= 0.0009:
        write_threshold(new_th)
        db_set_meta("last_adj_date", today)
        # optional info log
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | THRESH auto-tune: {th:.2f} -> {new_th:.2f} (winrate={wr*100:.0f}% over {total})")
# ---------------- Timeframe switcher (poll callback queries) ----------------
def tg_poll_callbacks(offset: int) -> Tuple[int, Optional[str]]:
    """
    Returns (new_offset, selected_tf_label or None)
    """
    if not BOT_TOKEN:
        return offset, None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {
        "timeout": 0,
        "offset": offset,
        "allowed_updates": ["callback_query"],
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
    except Exception:
        return offset, None
    if not isinstance(data, dict) or not data.get("ok"):
        return offset, None
    selected = None
    for upd in data.get("result", []):
        try:
            upd_id = int(upd.get("update_id"))
            offset = max(offset, upd_id + 1)
        except Exception:
            continue
        cq = upd.get("callback_query") or {}
        cqid = cq.get("id")
        cbdata = (cq.get("data") or "").strip()
        if cbdata.startswith("TF:"):
            tfl = cbdata.split(":", 1)[1].strip().upper()
            if tfl in TF_MAP:
                selected = tfl
                if cqid:
                    tg_answer_callback(cqid, f"Timeframe set: {tfl}")
    return offset, selected
def send_control_panel(tf_label: str):
    txt = f"Timeframe Control Panel\nCurrent TF: {tf_label}\n\nTap to switch:"
    tg_send_text(txt, reply_markup=tf_keyboard())
# ---------------- Smart Alert (ticker winrate) ----------------
def winrate_text(ticker: str) -> str:
    wins, total = db_win_rate_ticker(ticker, n=10)
    if total < 3:
        return "Win Rate (last 10): N/A"
    pct = int(round(100 * wins / max(1, total)))
    return f"Win Rate (last 10): {wins}/{total} ({pct}%)"


def make_signal_message(best: Pick, now_dt: datetime, entry: float, sl: float, tp: float, rsi: Optional[float], tf_label: str) -> str:
    sig_u = (best.signal or "").upper()
    if "EXPLOSIVE" in sig_u:
        title = "🚀 BOZORDA PORTLASH (SQUEEZE BREAKOUT)!"
    elif "STRONG" in sig_u:
        title = "[STRONG] SIGNAL"
    else:
        title = "SIGNAL"
    hhmm = now_dt.strftime("%H:%M")
    conf = int(round((best.p or 0.0) * 100))
    lines = [
        title,
        "",
        f"Ticker: {best.ticker}",
        f"Signal: {best.signal}",
        f"Confidence: {conf}%",
        f"Time: {hhmm}",
        f"Timeframe: {tf_label}",
        "",
        f"Entry: {entry:.4f}",
        f"Target (TP): {tp:.4f}",
        f"Safety (SL): {sl:.4f}",
        "",
        f"Reason: {best.reason or ''}",
        "",
        "Natija kiriting (faqat bitta marta):",
    ]
    return "\n".join(lines)

def main():
    global TF_LABEL, TF_INTERVAL
    global SLEEP_SEC
    global TOTAL_SCANS, DATA_ERRORS, LOW_PROBA_SKIPS, SIGNALS_SENT
    global sent_signals
    db_init()
    st = load_state()
    TF_LABEL = (st.get("tf_label") or "M5").upper()
    if TF_LABEL not in TF_MAP:
        TF_LABEL = "M5"
    TF_INTERVAL, _period = TF_MAP[TF_LABEL]
    SLEEP_SEC = sleep_sec_for_tf(TF_LABEL)
    last_key = st.get("last_key", "")
    last_time = float(st.get("last_time", 0.0) or 0.0)
    last_day = st.get("last_day")  # iso date
    upd_offset = int(st.get("upd_offset", 0) or 0)
    last_panel_ts = float(st.get("last_panel_ts", 0.0) or 0.0)
    print(f"[OK] BEST WATCH started. TF={TF_LABEL}. Stop: CTRL+C")
    # send control panel once at start
    send_control_panel(TF_LABEL)
    last_panel_ts = time.time()
    while True:
        try:
            now_dt = datetime.now()
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            today = now_dt.date().isoformat()
            # Poll callbacks (timeframe buttons)
            upd_offset, selected = tg_poll_callbacks(upd_offset)
            if selected and selected != TF_LABEL:
                TF_LABEL = selected
                TF_INTERVAL, _period = TF_MAP[TF_LABEL]
                SLEEP_SEC = sleep_sec_for_tf(TF_LABEL)
                print(f"{now_str} | TF switched to {TF_LABEL} (interval={TF_INTERVAL})")
                send_control_panel(TF_LABEL)
            # Daily session reset (dedupe)
            if last_day != today:
                print(f"{now_str} | NEW DAY session: reset sent_signals/duplicate cache")
                last_day = today
                sent_signals = set()
                last_key = ""
                last_time = 0.0
            # Outcome tracking + threshold tuning (lightweight each loop)
            outcome_tracker()
            maybe_adjust_threshold()
            # Run predictor for current TF
            out = run_multi_predict(TF_LABEL)
            picks = parse_picks(out)
            TOTAL_SCANS += len(picks)
            DATA_ERRORS += sum(1 for x in picks if x.reason == "data_error")
            LOW_PROBA_SKIPS += sum(1 for x in picks if x.reason == "low_proba")
            best = pick_best(picks)
            if not best:
                data_error = sum(1 for x in picks if x.reason == "data_error")
                low_proba = sum(1 for x in picks if x.reason == "low_proba")
                signal_cnt = sum(1 for x in picks if ("BUY" in x.signal.upper() or "SELL" in x.signal.upper()))
                print(f"{now_str} | BEST=NONE (all HOLD) | data_error={data_error} low_proba={low_proba} signal={signal_cnt}")
                time.sleep(SLEEP_SEC)
                continue
            side = (best.side or "").upper()
            if side not in ("BUY", "SELL"):
                print(f"{now_str} | BEST={best.ticker} INVALID_SIDE={best.side}")
                time.sleep(SLEEP_SEC)
                continue
            interval, period = TF_MAP.get(TF_LABEL, ("5m", "10d"))
            entry, atr14, rsi = fetch_entry_atr_rsi(best.ticker, interval=interval, period=period)
            if entry is None or atr14 is None or atr14 <= 0:
                print(f"{now_str} | BEST={best.ticker} data_error (no ATR/entry)")
                time.sleep(SLEEP_SEC)
                continue
            sl, tp = calc_sl_tp(entry, atr14, side)
            # SL/TP sanity
            if not sltp_valid(entry, sl, tp, side):
                print(f"{now_str} | [ERROR] Invalid SL/TP: {best.ticker} side={side} entry={entry:.4f} sl={sl:.4f} tp={tp:.4f} -> SKIP SEND")
                time.sleep(SLEEP_SEC)
                continue
            key = f"{best.ticker}:{best.signal}:{round(best.p,4)}:{TF_LABEL}"
            if key in sent_signals:
                print(f"{now_str} | DUPLICATE skip (set) {key}")
                time.sleep(SLEEP_SEC)
                continue
            if key == last_key and (time.time() - last_time) < DUPLICATE_TTL_SEC:
                print(f"{now_str} | DUPLICATE skip (ttl) {key}")
                time.sleep(SLEEP_SEC)
                continue
            # --- SEND FILTER: only p>0.80 OR EXPLOSIVE ---
            sig_u = (best.signal or "").upper()
            is_explosive = "EXPLOSIVE" in sig_u
            if (not is_explosive) and (float(best.p or 0.0) < 0.80):
                print(f"{now_str} | SKIP_SEND p<0.80 and not EXPLOSIVE | {best.ticker} {best.signal} p={best.p:.2f}")
                time.sleep(SLEEP_SEC)
                continue
            # --------------------------------------------
            # Send Telegram signal
            signal_id = str(uuid.uuid4())[:8]
            msg = make_signal_message(best, now_dt, entry, sl, tp, rsi, TF_LABEL)
            code, resp = send_signal_card(msg, signal_id)
            print(f"[TG] Telegram sent (buttons): {code}")
            if code == 200:
                SIGNALS_SENT += 1
                sent_signals.add(key)
                # save to DB (OPEN)
                db_insert_signal(
                    sig_id=signal_id,
                    ts=int(time.time()),
                    ticker=best.ticker,
                    side=side,
                    tf_label=TF_LABEL,
                    interval=interval,
                    p=float(best.p),
                    entry=float(entry),
                    sl=float(sl),
                    tp=float(tp),
                )
            # persist state
            last_key = key
            last_time = time.time()
            save_state({
                "tf_label": TF_LABEL,
                "last_key": last_key,
                "last_time": last_time,
                "last_day": last_day,
                "upd_offset": upd_offset,
                "last_panel_ts": last_panel_ts,
            })
            time.sleep(SLEEP_SEC)
        except KeyboardInterrupt:
            print("\n[STOP] stopped.")
            # optional: send final stats
            text = (
                f"BOT STOPPED\n"
                f"TOTAL_SCANS={TOTAL_SCANS}\n"
                f"DATA_ERRORS={DATA_ERRORS}\n"
                f"LOW_PROBA_SKIPS={LOW_PROBA_SKIPS}\n"
                f"SIGNALS_SENT={SIGNALS_SENT}\n"
            )
            tg_send_text(text)
            break
        except Exception as e:
            print("[WARN] error:", repr(e))
            time.sleep(10)
if __name__ == "__main__":
    main()



