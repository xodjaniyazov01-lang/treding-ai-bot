import os
import time
import json
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
import requests
import yfinance as yf
from dotenv import load_dotenv

# =========================
# CONFIG (.env)
# =========================
# .env example:
# BOT_TOKEN=123456:ABC...
# CHAT_ID=1106940684
# WATCHLIST=SPY,XLK,AAPL,MSFT,NVDA,TSLA,META,AMZN,GOOGL
# NEED_CONFIRM=2
# COOLDOWN_SEC=60
# YF_INTERVAL=5m
# YF_PERIOD=5d
# ATR_MULT_SL=1.5
# ATR_MULT_TP=3.0
load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHAT_ID = (os.getenv("CHAT_ID") or "").strip()
if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit("BOT_TOKEN yoki CHAT_ID topilmadi. .env faylga BOT_TOKEN va CHAT_ID yozing.")

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

WATCHLIST_ENV = (os.getenv("WATCHLIST") or "").strip()
WATCHLIST_FILE = Path("watchlist.txt")

NEED_CONFIRM = int(os.getenv("NEED_CONFIRM", "2"))
COOLDOWN_SEC = int(os.getenv("COOLDOWN_SEC", "60"))

YF_INTERVAL = os.getenv("YF_INTERVAL", "5m")  # 3m Yahoo'da yo'q, 5m ishlaydi
YF_PERIOD = os.getenv("YF_PERIOD", "5d")

ATR_MULT_SL = float(os.getenv("ATR_MULT_SL", "1.5"))
ATR_MULT_TP = float(os.getenv("ATR_MULT_TP", "3.0"))

MODEL_PATH = Path("model.joblib")
THRESHOLD_PATH = Path("threshold.txt")
LAST_SENT_PATH = Path("last_sent.txt")
PENDING_PATH = Path("pending_signal.json")

# feature order (must match train/predict)
FEATURES = [
    "side",
    "st_3m",
    "st_1h",
    "st_4h",
    "trend_align",
    "is_consolidation",
    "breakout",
    "volume_spike",
    "neckline_break",
    "atr_ratio",
    "rsi",
    "close_vs_ema",
]


def read_watchlist() -> list[str]:
    if WATCHLIST_ENV:
        return [x.strip().upper() for x in WATCHLIST_ENV.split(",") if x.strip()]
    if WATCHLIST_FILE.exists():
        return [x.strip().upper() for x in WATCHLIST_FILE.read_text(encoding="utf-8").splitlines() if x.strip()]
    return ["SPY", "XLK", "AAPL"]


def read_threshold(default: float = 0.6) -> float:
    if THRESHOLD_PATH.exists():
        try:
            t = float(THRESHOLD_PATH.read_text(encoding="utf-8", errors="ignore").strip())
            if 0.05 <= t <= 0.95:
                return t
        except Exception:
            pass
    return default


def tg_send_signal(text: str, signal_id: str):
    # Buttons: feedback bot uses callback_data = WIN|<id> or LOSS|<id>
    keyboard = {
        "inline_keyboard": [[
            {"text": "WIN ✅", "callback_data": f"WIN|{signal_id}"},
            {"text": "LOSS ❌", "callback_data": f"LOSS|{signal_id}"},
        ]]
    }
    r = requests.post(
        f"{BASE}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "reply_markup": keyboard},
        timeout=20,
    )
    return r.status_code, r.text


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    c = df["Close"].astype(float)

    prev_close = c.shift(1)
    tr = pd.concat([
        (h - l).abs(),
        (h - prev_close).abs(),
        (l - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if np.isfinite(atr) else float(tr.iloc[-1])


def fetch_ohlcv(ticker: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        period=YF_PERIOD,
        interval=YF_INTERVAL,
        progress=False,
        auto_adjust=False,
        group_by="column",
        threads=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"No candles for {ticker}")

    # Sometimes columns are MultiIndex
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    need = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing columns for {ticker}: {missing}")

    return df.dropna().copy()


def build_features_from_candles(df: pd.DataFrame, side: str) -> dict:
    # NOTE: Bu demo feature'lar. Siz keyin ularni yanada kuchaytirasiz.
    close = df["Close"].astype(float)
    vol = df["Volume"].astype(float)

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    rs = gain.rolling(14).mean() / (loss.rolling(14).mean().replace(0, np.nan))
    rsi = (100 - (100 / (1 + rs))).iloc[-1]
    rsi = float(rsi) if np.isfinite(rsi) else 50.0

    # EMA
    ema = close.ewm(span=20, adjust=False).mean().iloc[-1]
    close_vs_ema = 1 if close.iloc[-1] >= ema else 0

    # ATR ratio
    atr = compute_atr(df, 14)
    atr_ratio = float(atr / close.iloc[-1]) if close.iloc[-1] else 0.005

    # very simple heuristics for breakout/volume_spike
    breakout = 1 if close.iloc[-1] > close.rolling(20).max().iloc[-2] else 0
    vol_ma = vol.rolling(20).mean().iloc[-1]
    volume_spike = 1 if (vol_ma and vol.iloc[-1] > 1.5 * vol_ma) else 0

    # placeholders for your multi-timeframe signals
    st_3m = 1 if side == "BUY" else 0
    st_1h = 1 if side == "BUY" else 0
    st_4h = 1 if side == "BUY" else 0
    trend_align = 1

    is_consolidation = 0
    neckline_break = 0

    return {
        "side": 1 if side == "BUY" else 0,
        "st_3m": int(st_3m),
        "st_1h": int(st_1h),
        "st_4h": int(st_4h),
        "trend_align": int(trend_align),
        "is_consolidation": int(is_consolidation),
        "breakout": int(breakout),
        "volume_spike": int(volume_spike),
        "neckline_break": int(neckline_break),
        "atr_ratio": float(atr_ratio),
        "rsi": float(rsi),
        "close_vs_ema": int(close_vs_ema),
    }


def predict_one(model, feat: dict) -> float:
    X = pd.DataFrame([[feat.get(k) for k in FEATURES]], columns=FEATURES)
    p = float(model.predict_proba(X)[0, 1])
    return p


def to_signal(p: float, th: float, side: str) -> str:
    # side = intended direction for this ticker (BUY by default)
    if side == "BUY":
        if p >= max(0.9, th + 0.25):
            return "STRONG_BUY"
        if p >= th:
            return "BUY"
        return "HOLD"
    else:
        # for SELL we treat low p as sell
        if p <= min(0.1, 1 - (th + 0.25)):
            return "STRONG_SELL"
        if p <= (1 - th):
            return "SELL"
        return "HOLD"


def strength_score(p: float, side: str) -> float:
    return p if side == "BUY" else (1.0 - p)


def calc_plan(df: pd.DataFrame, direction: str) -> tuple[float, float, float]:
    entry = float(df["Close"].astype(float).iloc[-1])
    atr = compute_atr(df, 14)
    if direction == "BUY":
        sl = entry - atr * ATR_MULT_SL
        tp = entry + atr * ATR_MULT_TP
    else:
        sl = entry + atr * ATR_MULT_SL
        tp = entry - atr * ATR_MULT_TP
    return entry, sl, tp


def save_pending(signal_id: str, payload: dict):
    PENDING_PATH.write_text(json.dumps({"signal_id": signal_id, **payload}, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    if not MODEL_PATH.exists():
        raise SystemExit("model.joblib topilmadi. Avval: python train.py")

    model = joblib.load(MODEL_PATH)
    th = read_threshold(0.6)

    watch = read_watchlist()
    print("REALTIME WATCH TOP started. Stop: CTRL+C")

    last_sent = LAST_SENT_PATH.read_text(encoding="utf-8").strip() if LAST_SENT_PATH.exists() else ""
    last_sent_time = 0.0

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        rows = []
        errors = []
        for t in watch:
            side = "BUY"  # default
            if t.startswith("-"):
                t = t[1:]
                side = "SELL"
            try:
                df = fetch_ohlcv(t)
                feat = build_features_from_candles(df, side)
                p = predict_one(model, feat)
                sig = to_signal(p, th, side)
                score = strength_score(p, side)
                entry, sl, tp = calc_plan(df, "BUY" if side == "BUY" else "SELL")
                rows.append({
                    "ticker": t,
                    "side": side,
                    "p": p,
                    "sig": sig,
                    "score": score,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "features": feat,
                })
            except Exception as e:
                errors.append(f"{t}: {e}")

        if errors:
            # don't stop, just show
            for e in errors[:3]:
                print("⚠️", e)

        if not rows:
            print(f"{now} | FINAL= (no data)")
            time.sleep(20)
            continue

        # sort by strongest score
        rows.sort(key=lambda x: x["score"], reverse=True)

        # pick best non-HOLD first
        best = None
        for r in rows:
            if r["sig"] != "HOLD":
                best = r
                break
        if best is None:
            # all HOLD
            print(f"{now} | FINAL=HOLD (all tickers HOLD)")
            time.sleep(20)
            continue

        direction = "BUY" if best["side"] == "BUY" else "SELL"
        final = f"{best['sig'].replace('_', ' ')}"

        # Build message
        top_list = " | ".join([f"{r['ticker']}={r['sig']}({r['p']:.2f})" for r in rows[:min(6, len(rows))]])
        msg = (
            f"FINAL: {final}\n"
            f"TOP: {best['ticker']} ({direction}) p={best['p']:.2f} th={th:.2f}\n"
            f"LIST: {top_list}\n"
            f"TIME: {now}\n\n"
            f"PLAN: entry={best['entry']:.2f}  SL={best['sl']:.2f}  TP={best['tp']:.2f}\n\n"
            f"Natija kiriting:"  # buttons
        )

        # cooldown / dedupe
        can_send = (time.time() - last_sent_time) >= COOLDOWN_SEC
        is_same = (last_sent == f"{best['ticker']}|{final}")

        print(f"{now} | FINAL={final} | TOP={best['ticker']} p={best['p']:.2f}")

        if (not is_same) or can_send:
            signal_id = uuid.uuid4().hex[:10]
            payload = {
                "ticker": best["ticker"],
                "direction": direction,
                "signal": final,
                "p": best["p"],
                "threshold": th,
                "entry": best["entry"],
                "sl": best["sl"],
                "tp": best["tp"],
                "features": best["features"],
                "created_at": now,
            }
            save_pending(signal_id, payload)

            code, txt = tg_send_signal(msg, signal_id)
            print(f"Telegram sent: {code}")
            if code == 200:
                last_sent = f"{best['ticker']}|{final}"
                LAST_SENT_PATH.write_text(last_sent, encoding="utf-8")
                last_sent_time = time.time()
            else:
                # show first part of error
                print("Telegram error:", (txt or "")[:200])

        time.sleep(20)


if __name__ == "__main__":
    main()
