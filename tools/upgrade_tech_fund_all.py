from __future__ import annotations
import os, re, json, time
from pathlib import Path
from datetime import datetime
ROOT = Path.cwd()
SRC = ROOT / "src" / "trade_ai"
LEGACY = SRC / "legacy"
APP = SRC / "app"
def backup(path: Path):
    if path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = path.with_suffix(path.suffix + f".bak_{ts}")
        bak.write_bytes(path.read_bytes())
        print(f"[backup] {path} -> {bak.name}")
def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    backup(path)
    path.write_text(text, encoding="utf-8")
    print(f"[write] {path}")
fundamentals_cache_py = r'''from __future__ import annotations
import json, time, math
from pathlib import Path
try:
    import yfinance as yf
except Exception:
    yf = None
ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "fundamentals_cache.json"
TTL_SEC = 24 * 3600  # 24 soat
def _load() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}
def _save(d: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
def _pick(info: dict) -> dict:
    def g(k, default=None):
        v = info.get(k, default)
        return v
    mc = g("marketCap", None)
    mc_log = None
    if isinstance(mc, (int, float)) and mc and mc > 0:
        mc_log = float(math.log10(mc))
    out = {
        "sector": g("sector", "NA") or "NA",
        "industry": g("industry", "NA") or "NA",
        "market_cap_log": mc_log,
        "beta": g("beta", None),
        "trailing_pe": g("trailingPE", None),
        "forward_pe": g("forwardPE", None),
        "price_to_book": g("priceToBook", None),
        "profit_margins": g("profitMargins", None),
        "operating_margins": g("operatingMargins", None),
        "revenue_growth": g("revenueGrowth", None),
        "earnings_growth": g("earningsGrowth", None),
        "debt_to_equity": g("debtToEquity", None),
        "current_ratio": g("currentRatio", None),
        "dividend_yield": g("dividendYield", None),
    }
    return out
def get_fundamentals(ticker: str) -> dict:
    if yf is None:
        return {}
    t = (ticker or "").upper().strip()
    if not t:
        return {}
    cache = _load()
    rec = cache.get(t)
    now = int(time.time())
    if isinstance(rec, dict) and (now - int(rec.get("_ts", 0))) < TTL_SEC:
        out = dict(rec)
        out.pop("_ts", None)
        return out
    try:
        info = yf.Ticker(t).info or {}
        out = _pick(info)
        cache[t] = {"_ts": now, **out}
        _save(cache)
        return out
    except Exception:
        return {}
'''
multi_predict_py = r'''from __future__ import annotations
import argparse
import os
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import yfinance as yf
from trade_ai.legacy.fundamentals_cache import get_fundamentals
MODEL_PATH = Path("model.joblib")
WATCHLIST = Path("watchlist.txt")
THRESH_PATH = Path("threshold.txt")
def load_threshold(default=0.55):
    try:
        raw = THRESH_PATH.read_text(encoding="utf-8").strip()
        raw = raw.replace("\ufeff", "").strip()
        return float(raw)
    except Exception:
        return default
def load_watchlist():
    if not WATCHLIST.exists():
        return ["SPY", "XLK", "AAPL"]
    tickers = []
    txt = WATCHLIST.read_text(encoding="utf-8", errors="ignore")
    txt = txt.replace("\ufeff", "")
    for line in txt.splitlines():
        t = line.strip().upper()
        if t and not t.startswith("#"):
            tickers.append(t)
    return tickers
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()
def atr(df_: pd.DataFrame, n: int = 14) -> pd.Series:
    high = df_["High"]
    low = df_["Low"]
    close = df_["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()
def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / (down + 1e-9)
    return 100 - (100 / (1 + rs))
def download_flat(ticker: str):
    # ✅ TECH uchun M5 bazasi
    df = yf.download(
        ticker,
        period="10d",
        interval="5m",
        auto_adjust=False,
        group_by="column",
        progress=False
    )
    if df is None or len(df) < 300:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    need = {"Open", "High", "Low", "Close", "Volume"}
    if not need.issubset(df.columns):
        return None
    df = df.dropna().copy()
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    return df
def build_features(ticker: str):
    df = download_flat(ticker)
    if df is None:
        return None
    # Resample (1h, 4h) trend align uchun
    df5 = df  # 5m base
    df1h = df.resample("1h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    df4h = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    if len(df5) < 200 or len(df1h) < 60 or len(df4h) < 30:
        return None
    close = df5["Close"]
    high = df5["High"]
    low = df5["Low"]
    vol = df5["Volume"]
    last_close = float(close.iloc[-1])
    atr5 = float(atr(df5).iloc[-1])
    atr_ratio = float(atr5 / max(last_close, 1e-9))
    rsi5 = float(rsi(close).iloc[-1])
    ema20 = float(ema(close, 20).iloc[-1])
    close_vs_ema = int(last_close > ema20)
    rolling_high = float(high.rolling(20).max().iloc[-2])
    rolling_low  = float(low.rolling(20).min().iloc[-2])
    breakout = int(last_close > rolling_high or last_close < rolling_low)
    vol_now = float(vol.iloc[-1])
    vol_mean = float(vol.rolling(20).mean().iloc[-2])
    volume_spike = int(vol_now > (vol_mean * 1.5 if vol_mean > 0 else 0))
    is_consolidation = int(atr_ratio < 0.0030)  # M5 uchun biroz moslashtirildi
    # Trend (ema cross)
    st_5m = int(ema(close, 20).iloc[-1] > ema(close, 50).iloc[-1])
    st_1h = int(ema(df1h["Close"], 20).iloc[-1] > ema(df1h["Close"], 50).iloc[-1])
    st_4h = int(ema(df4h["Close"], 20).iloc[-1] > ema(df4h["Close"], 50).iloc[-1])
    trend_align = int(st_1h == st_4h)
    side = "BUY" if st_4h == 1 else "SELL"
    neckline_break = breakout
    # Extra TECH
    ret_1 = float(close.pct_change(1).iloc[-1])
    ret_5 = float(close.pct_change(5).iloc[-1]) if len(close) > 6 else 0.0  # ~25m
    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    macd = ema12 - ema26
    macd_sig = ema(macd, 9)
    macd_hist = float((macd - macd_sig).iloc[-1])
    ma20 = close.rolling(20).mean()
    sd20 = close.rolling(20).std()
    upper = ma20 + 2 * sd20
    lower = ma20 - 2 * sd20
    bb_pos = float((last_close - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1] + 1e-9)) if len(close) > 25 else 0.5
    bb_pos = float(np.clip(bb_pos, 0.0, 1.0))
    vmean = vol.rolling(30).mean()
    vstd = vol.rolling(30).std()
    vol_z = float((vol_now - vmean.iloc[-1]) / (vstd.iloc[-1] + 1e-9)) if len(vol) > 35 else 0.0
    volat = float(close.pct_change().rolling(30).std().iloc[-1]) if len(close) > 40 else 0.0
    # FUNDAMENTAL (cache)
    fund = get_fundamentals(ticker) or {}
    sample = {
        # Old keys (compat)
        "pattern_name": "auto_pattern",
        "side": side,
        "st_3m": st_5m,     # eski nom saqlanadi (endi ma'nosi 5m)
        "st_1h": st_1h,
        "st_4h": st_4h,
        "trend_align": trend_align,
        "is_consolidation": is_consolidation,
        "breakout": breakout,
        "volume_spike": volume_spike,
        "neckline_break": neckline_break,
        "atr_ratio": round(atr_ratio, 6),
        "rsi": round(rsi5, 2),
        "close_vs_ema": close_vs_ema,
        # New TECH
        "ret_1": round(ret_1, 6),
        "ret_5": round(ret_5, 6),
        "macd_hist": round(macd_hist, 6),
        "bb_pos": round(bb_pos, 4),
        "vol_z": round(vol_z, 4),
        "volatility": round(volat, 6),
    }
    # Add FUND keys (may be None)
    sample.update(fund)
    return sample
def to_signal(p_win: float, side: str, th: float):
    strong_th = min(0.90, th + 0.25)
    if p_win >= strong_th:
        return "STRONG_BUY" if side == "BUY" else "STRONG_SELL"
    if p_win >= th:
        return "BUY" if side == "BUY" else "SELL"
    return "HOLD"
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--ticker", default="")
    args = ap.parse_args()
    if not MODEL_PATH.exists():
        print("❌ model.joblib topilmadi. Avval train bo‘lishi kerak.")
        return
    model = joblib.load(MODEL_PATH)
    th = load_threshold()
    tickers = [args.ticker.upper()] if args.ticker else load_watchlist()
    for t in tickers:
        sample = build_features(t)
        if sample is None:
            print(f"{t}: HOLD (p=0.50)")
            continue
        p_win = float(model.predict_proba(pd.DataFrame([sample]))[0][1])
        sig = to_signal(p_win, sample.get("side", "BUY"), th)
        side = sample.get("side", "BUY")
        print(f"{t}: {sig} (p={p_win:.2f}, th={th:.2f}, side={side})")
if __name__ == "__main__":
    main()
'''
watch_best_py = r'''from __future__ import annotations
import re
import json
import time
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple
from trade_ai.config.settings import BOT_TOKEN, CHAT_ID
from trade_ai.legacy.telegram_alert import send_signal_card
from trade_ai.legacy.multi_predict import build_features
try:
    import yfinance as yf
except Exception:
    yf = None
ROOT = Path(__file__).resolve().parents[3]
LEGACY = ROOT / "src" / "trade_ai" / "legacy"
WATCHLIST = ROOT / "watchlist.txt"
STATE_FILE = ROOT / "data" / "last_best_signal.json"
PENDING_FILE = ROOT / "pending_signal.json"
def _clean_ticker(x: str) -> str:
    return (x or "").replace("\ufeff", "").strip().upper()
@dataclass
class Pick:
    ticker: str
    signal: str
    p: float
    side: str
    threshold: Optional[float] = None
def load_watchlist() -> List[str]:
    if not WATCHLIST.exists():
        return ["SPY", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL", "XLK"]
    out = []
    txt = WATCHLIST.read_text(encoding="utf-8", errors="ignore").replace("\ufeff", "")
    for line in txt.splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        out.append(_clean_ticker(t))
    return out
def run_multi_predict() -> str:
    mp = LEGACY / "multi_predict.py"
    if not mp.exists():
        raise RuntimeError(f"legacy multi_predict.py topilmadi: {mp}")
    cmd = [sys.executable, str(mp), "--auto"]
    return subprocess.check_output(cmd, text=True, errors="ignore", cwd=str(ROOT))
def parse_lines(stdout: str) -> List[Pick]:
    picks: List[Pick] = []
    rx = re.compile(
        r"^\s*([A-Z\.\-]+)\s*:\s*([A-Z_]+)\s*\(p\s*=\s*([0-9.]+)"
        r"(?:,\s*th\s*=\s*([0-9.]+))?"
        r"(?:,\s*side\s*[:=]\s*([A-Z]+))?",
        re.IGNORECASE
    )
    for line in stdout.splitlines():
        m = rx.search(line)
        if not m:
            continue
        ticker = m.group(1).upper()
        sig = m.group(2).upper()
        p = float(m.group(3))
        th = float(m.group(4)) if m.group(4) else None
        side = (m.group(5) or "").upper() or ("SELL" if "SELL" in sig else "BUY")
        picks.append(Pick(ticker=ticker, signal=sig, p=p, side=side, threshold=th))
    return picks
def strength_score(sig: str, p: float) -> float:
    bonus = 0.05 if sig.startswith("STRONG_") else 0.0
    if "BUY" in sig or "SELL" in sig:
        return p + bonus
    return 0.0
def pick_best(picks: List[Pick]) -> Optional[Pick]:
    cands = []
    for x in picks:
        u = x.signal.upper()
        if "HOLD" in u or "CONFLICT" in u:
            continue
        if ("BUY" in u) or ("SELL" in u):
            cands.append(x)
    if not cands:
        return None
    cands.sort(key=lambda x: strength_score(x.signal, x.p), reverse=True)
    return cands[0]
def fetch_atr_entry(ticker: str) -> Tuple[Optional[float], Optional[float]]:
    if yf is None:
        return None, None
    try:
        df = yf.download(ticker, period="10d", interval="5m", progress=False)
    except Exception:
        return None, None
    if df is None or len(df) < 50:
        return None, None
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = [c[0] for c in df.columns]
    for col in ["High", "Low", "Close"]:
        if col not in df.columns:
            return None, None
    high = df["High"]; low = df["Low"]; close = df["Close"]
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = tr1.combine(tr2, max).combine(tr3, max)
    atr = true_range.rolling(14).mean()
    entry = float(close.iloc[-1])
    atr14 = float(atr.iloc[-1]) if atr.iloc[-1] == atr.iloc[-1] else None
    return entry, atr14
def calc_sl_tp(entry: float, atr14: float, direction: str) -> Tuple[float, float]:
    sl_dist = 2.0 * atr14
    tp_dist = 3.0 * atr14
    if direction == "BUY":
        return entry - sl_dist, entry + tp_dist
    return entry + sl_dist, entry - tp_dist
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}
    return {}
def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
def save_pending(signal_id: str, best: Pick, direction: str, tf: str, sample: Optional[dict], entry, sl, tp) -> None:
    payload = {
        "id": signal_id,
        "data": {
            "ticker": best.ticker,
            "signal": best.signal,
            "p": float(best.p),
            "side": direction,
            "tf": tf,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "sample": sample,
            "ts": int(time.time()),
        },
    }
    PENDING_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
def _make_message(best: Pick, now: str, direction: str, tf: str, entry, sl, tp, sample: Optional[dict]) -> str:
    sig = best.signal.upper()
    emo = "🟢" if "BUY" in sig else ("🔴" if "SELL" in sig else "⚪")
    lines = [
        f"✅ BEST SIGNAL {emo}",
        "",
        f"Ticker: {best.ticker}",
        f"TF: {tf}",
        f"Side: {direction}",
        f"Signal: {best.signal} (p={best.p:.2f})",
    ]
    if sample and isinstance(sample, dict):
        sector = sample.get("sector")
        pe = sample.get("trailing_pe")
        if sector:
            lines.append(f"Sector: {sector}")
        if pe is not None:
            try:
                lines.append(f"P/E: {float(pe):.2f}")
            except Exception:
                pass
    if entry is not None and sl is not None and tp is not None:
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = (reward / risk) if risk else 0.0
        lines += [
            "",
            f"Entry: {entry:.2f}",
            f"StopLoss: {sl:.2f}",
            f"TakeProfit: {tp:.2f}",
            f"RR: 1:{rr:.2f}",
        ]
    lines += ["", f"Time: {now}"]
    return "\n".join(lines) + "\n"
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ BOT_TOKEN yoki CHAT_ID yo‘q. .env tekshiring.")
        raise SystemExit(1)
    tickers = load_watchlist()
    cooldown_sec = 1800  # 30 min
    sleep_sec = 60       # 1 min
    print("🟢 BEST WATCH started (TECH+FUND, TF=M5). Stop: CTRL+C")
    state = load_state()
    last_key = state.get("last_key", "")
    last_time = float(state.get("last_time", 0))
    while True:
        try:
            out = run_multi_predict()
            picks = parse_lines(out)
            best = pick_best(picks)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            if not best:
                print(f"{now} | BEST=NONE (all HOLD)")
                time.sleep(sleep_sec)
                continue
            direction = (best.side or "").upper()
            if direction not in ("BUY", "SELL"):
                direction = "SELL" if "SELL" in best.signal.upper() else "BUY"
            tf = "M5"
            # sample (TECH+FUND)
            sample = build_features(best.ticker)
            if isinstance(sample, dict):
                sample["side"] = direction
            else:
                sample = None
            entry, atr14 = fetch_atr_entry(best.ticker)
            sl = tp = None
            if entry is not None and atr14 is not None:
                sl, tp = calc_sl_tp(entry, atr14, direction)
            # ✅ spamga qarshi key (entry qo‘shilmaydi)
            key = f"{best.ticker}|{best.signal}|{round(best.p, 2)}"
            can_send = (key != last_key) or ((time.time() - last_time) >= cooldown_sec)
            msg = _make_message(best, now, direction, tf, entry, sl, tp, sample)
            print(f"{now} | BEST={best.ticker} {best.signal} p={best.p:.2f}")
            if can_send:
                signal_id = f"{best.ticker}-{uuid.uuid4().hex[:8]}"
                save_pending(signal_id, best, direction, tf, sample, entry, sl, tp)
                code, resp = send_signal_card(msg, signal_id)
                print(f"📩 Telegram sent (buttons): {code}")
                if code != 200:
                    print("⚠️ Telegram resp:", str(resp)[:200])
                last_key = key
                last_time = time.time()
                save_state({"last_key": last_key, "last_time": last_time})
            time.sleep(sleep_sec)
        except KeyboardInterrupt:
            print("\n🛑 stopped.")
            break
        except Exception as e:
            print("⚠️ error:", repr(e))
            time.sleep(10)
if __name__ == "__main__":
    main()
'''
telegram_feedback_bot_py = r'''from __future__ import annotations
import json
import time
import sqlite3
from pathlib import Path
from typing import Tuple, Optional
import requests
from trade_ai.config.settings import BOT_TOKEN, CHAT_ID
BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
ROOT = Path(__file__).resolve().parents[3]
PENDING = ROOT / "pending_signal.json"
OFFSET_FILE = ROOT / ".tg_offset"
DB_PATH = ROOT / "data" / "learn.db"
MODEL_PATH = ROOT / "model.joblib"
THRESH_PATH = ROOT / "threshold.txt"
def api(method: str) -> str:
    return f"{BASE}/{method}"
def ensure_files():
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    if not PENDING.exists():
        PENDING.write_text(json.dumps({"id": "", "data": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not OFFSET_FILE.exists():
        OFFSET_FILE.write_text("0", encoding="utf-8")
def load_pending():
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except Exception:
        return {"id": "", "data": {}}
def save_pending(obj):
    PENDING.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
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
    if len(data) < 30:
        return False, f"Data kam: {len(data)} ta (kamida 30 ta WIN/LOSS kerak)"
    df = pd.DataFrame(data)
    if "label" not in df.columns:
        return False, "label yo‘q"
    # label
    df["label"] = pd.to_numeric(df["label"], errors="coerce")
    df = df.dropna(subset=["label"]).copy()
    df["label"] = df["label"].astype(int)
    counts = df["label"].value_counts().to_dict()
    if len(counts) < 2:
        return False, f"Label faqat bitta: {counts} (WIN va LOSS ikkalasi kerak)"
    # Features: labeldan boshqa hammasi
    X = df.drop(columns=["label"]).copy()
    y = df["label"].copy()
    # Object -> categorical
    cat_cols = [c for c in X.columns if X[c].dtype == "object"]
    num_cols = [c for c in X.columns if c not in cat_cols]
    # Fill missing
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
    # Dataset katta bo‘lsa HGB, kichik bo‘lsa Logistic
    use_hgb = len(df) >= 250
    if use_hgb:
        clf = HistGradientBoostingClassifier(
            max_depth=6,
            learning_rate=0.06,
            max_iter=250,
        )
    else:
        clf = LogisticRegression(max_iter=900, class_weight="balanced")
    model = Pipeline([("pre", pre), ("clf", clf)])
    # class imbalance uchun sample_weight (HGB holatda foydali)
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
    # threshold: PR curve bo‘yicha best F1
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
        f"✅ TRAIN DONE (TECH+FUND)\n"
        f"rows={len(df)} labels={counts}\n"
        f"model={'HGB' if use_hgb else 'LogReg'}\n"
        f"threshold={best_th:.3f} | ROC_AUC={roc:.3f} | PR_AUC={pr:.3f}\n\n"
        f"{rep}"
    )
    return True, msg
def poll():
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: BOT_TOKEN yoki CHAT_ID yo‘q. .env tekshir.")
        return
    ensure_files()
    print("🟢 FEEDBACK BOT started (SQL + Auto-train). Stop: CTRL+C")
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
                pending = load_pending()
                if pending.get("id") != signal_id:
                    answer_callback(cb_id, "Pending signal topilmadi yoki eski signal")
                    continue
                d = pending.get("data", {})
                sample = d.get("sample")
                if not isinstance(sample, dict):
                    answer_callback(cb_id, "Sample yo‘q (feature saqlanmagan)")
                    save_pending({"id": "", "data": {}})
                    continue
                label = 1 if action == "WIN" else 0
                insert_labeled(signal_id, d, label)
                save_pending({"id": "", "data": {}})
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
                    send_msg(f"✅ Saved {action} (SQL). TRAIN: {report}")
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except Exception as e:
            print("error:", e)
            time.sleep(2)
if __name__ == "__main__":
    poll()
'''
def main():
    write_text(LEGACY / "fundamentals_cache.py", fundamentals_cache_py)
    write_text(LEGACY / "multi_predict.py", multi_predict_py)
    write_text(APP / "watch_best.py", watch_best_py)
    write_text(LEGACY / "telegram_feedback_bot.py", telegram_feedback_bot_py)
    print("\n✅ DONE. Quick test (features):")
    # quick import test
    import importlib
    mp = importlib.import_module("trade_ai.legacy.multi_predict")
    sample = mp.build_features("AAPL")
    print("AAPL sample keys:", list(sample.keys())[:12], "... total:", len(sample) if sample else None)
    print("OK")
if __name__ == "__main__":
    main()
