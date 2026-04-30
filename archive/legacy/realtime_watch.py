import os, time, json
import yfinance as yf
import pandas as pd
import joblib

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "model.joblib")
SIGNALS_LOG = os.path.join(HERE, "signals.log")

TH_OK = 0.65
TH_STRONG = 0.85

SLEEP_SEC = 300  # 5 minut

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def atr(df_, n=14):
    high = df_["High"]
    low = df_["Low"]
    close = df_["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / (down + 1e-9)
    return 100 - (100 / (1 + rs))

def build_features(ticker: str):
    df = yf.download(
        ticker,
        period="5d",
        interval="1m",
        auto_adjust=False,
        group_by="column",
        progress=False
    )

    if df is None or len(df) < 200:
        return None

    # ✅ FIX: MultiIndex bo‘lsa tekislaymiz
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        print(f"⚠️ {ticker}: ustunlar yetishmayapti -> {list(df.columns)}")
        return None

    df = df.dropna().copy()

    # resample
    df3 = df.resample("3min").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

    df1h = df.resample("1h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

    df4h = df.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

    if len(df3) < 60 or len(df1h) < 20 or len(df4h) < 10:
        return None

    last_close = float(df3["Close"].iloc[-1])

    atr3 = atr(df3).iloc[-1]
    atr_ratio = float(atr3 / max(last_close, 1e-9))

    rsi3 = float(rsi(df3["Close"]).iloc[-1])

    ema20 = float(ema(df3["Close"], 20).iloc[-1])
    close_vs_ema = int(last_close > ema20)

    rolling_high = float(df3["High"].rolling(20).max().iloc[-2])
    breakout = int(last_close > rolling_high)

    vol_now = float(df3["Volume"].iloc[-1])
    vol_mean = float(df3["Volume"].rolling(20).mean().iloc[-2])
    volume_spike = int(vol_now > (vol_mean * 1.5 if vol_mean > 0 else 0))

    is_consolidation = int(atr_ratio < 0.0025)

    st_3m = int(ema(df3["Close"], 20).iloc[-1] > ema(df3["Close"], 50).iloc[-1])
    st_1h = int(ema(df1h["Close"], 20).iloc[-1] > ema(df1h["Close"], 50).iloc[-1])
    st_4h = int(ema(df4h["Close"], 20).iloc[-1] > ema(df4h["Close"], 50).iloc[-1])

    trend_align = int(st_1h == st_4h)
    neckline_break = breakout
    side = "BUY" if st_4h == 1 else "SELL"

    sample = {
        "pattern_name": "auto_pattern",
        "side": side,
        "st_3m": st_3m,
        "st_1h": st_1h,
        "st_4h": st_4h,
        "trend_align": trend_align,
        "is_consolidation": is_consolidation,
        "breakout": breakout,
        "volume_spike": volume_spike,
        "neckline_break": neckline_break,
        "atr_ratio": round(atr_ratio, 6),
        "rsi": round(rsi3, 2),
        "close_vs_ema": close_vs_ema
    }
    return sample, last_close

def predict_prob(sample: dict) -> float:
    model = joblib.load(MODEL_PATH)
    df = pd.DataFrame([sample])
    return float(model.predict_proba(df)[0][1])

def classify(p: float, side: str) -> str:
    side = side.upper().strip()
    if p >= TH_STRONG:
        return f"STRONG_{side}"
    if p >= TH_OK:
        return side
    return "HOLD"

def decide_3(spy_cls: str, xlk_cls: str, aapl_cls: str) -> str:
    buy_set = {"BUY", "STRONG_BUY"}
    sell_set = {"SELL", "STRONG_SELL"}

    if spy_cls in buy_set and xlk_cls in buy_set and aapl_cls in buy_set:
        if "STRONG" in spy_cls or "STRONG" in xlk_cls or "STRONG" in aapl_cls:
            return "STRONG BUY (SPY+XLK+AAPL)"
        return "BUY (SPY+XLK+AAPL)"

    if spy_cls in sell_set and xlk_cls in sell_set and aapl_cls in sell_set:
        if "STRONG" in spy_cls or "STRONG" in xlk_cls or "STRONG" in aapl_cls:
            return "STRONG SELL (SPY+XLK+AAPL)"
        return "SELL (SPY+XLK+AAPL)"

    return "HOLD (no 3-confirm)"

def log_line(text: str):
    with open(SIGNALS_LOG, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def main():
    print("🟢 REALTIME WATCH started. Stop: CTRL+C")
    while True:
        try:
            pack = {}
            for t in ["SPY", "XLK", "AAPL"]:
                built = build_features(t)
                if built is None:
                    pack[t] = {"cls": "HOLD", "p": None}
                    continue
                sample, _price = built
                p = predict_prob(sample)
                cls = classify(p, sample["side"])
                pack[t] = {"cls": cls, "p": p}

            spy = pack["SPY"]["cls"]
            xlk = pack["XLK"]["cls"]
            aapl = pack["AAPL"]["cls"]
            final = decide_3(spy, xlk, aapl)

            line = (
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"SPY={spy}({pack['SPY']['p'] and round(pack['SPY']['p'],2)}) "
                f"XLK={xlk}({pack['XLK']['p'] and round(pack['XLK']['p'],2)}) "
                f"AAPL={aapl}({pack['AAPL']['p'] and round(pack['AAPL']['p'],2)}) | "
                f"FINAL={final}"
            )
            print(line)
            log_line(line)

            with open(os.path.join(HERE, "last_signal.json"), "w", encoding="utf-8") as f:
                json.dump({"time": time.time(), "pack": pack, "final": final}, f, ensure_ascii=False, indent=2)

            time.sleep(SLEEP_SEC)

        except KeyboardInterrupt:
            print("\n🛑 stopped.")
            break
        except Exception as e:
            print("⚠️ error:", e)
            time.sleep(10)

if __name__ == "__main__":
    main()
