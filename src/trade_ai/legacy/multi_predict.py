from __future__ import annotations
import argparse
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
try:
    import pandas as pd
except Exception:
    pd = None
try:
    import yfinance as yf
except Exception:
    yf = None
ROOT = Path(__file__).resolve().parents[3]
WATCHLIST_PATH = ROOT / "watchlist.txt"
THRESH_PATH = ROOT / "threshold.txt"
TF_MAP = {
    "M5":  ("5m",  "10d"),
    "M15": ("15m", "30d"),
    "H1":  ("60m", "180d"),
    "H4":  ("60m", "180d"),
}
# ATR as % of price
MIN_ATR_PCT_BY_TF = {"M5": 0.0009, "M15": 0.0011, "H1": 0.0016, "H4": 0.0022}
WIDE_ATR_PCT_BY_TF = {"M5": 0.0060, "M15": 0.0080, "H1": 0.0120, "H4": 0.0180}
def safe_ascii(x: object) -> str:
    try:
        s = str(x)
    except Exception:
        s = repr(x)
    return s.encode("ascii", "backslashreplace").decode("ascii")
def is_finite(x: Optional[float]) -> bool:
    try:
        return x is not None and float(x) == float(x) and math.isfinite(float(x))
    except Exception:
        return False
def fmt_num(x: Optional[float], nd: int = 4) -> str:
    return f"{float(x):.{nd}f}" if is_finite(x) else "NA"
def read_threshold(default: float = 0.55) -> float:
    try:
        raw = THRESH_PATH.read_text(encoding="utf-8", errors="ignore").replace("\ufeff", "").strip()
        v = float(raw)
        return max(0.20, min(0.85, v))
    except Exception:
        return default
def read_watchlist() -> List[str]:
    if not WATCHLIST_PATH.exists():
        return ["SPY"]
    raw = WATCHLIST_PATH.read_text(encoding="utf-8", errors="ignore")
    out: List[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.extend([p.strip() for p in line.replace(",", " ").split() if p.strip()])
    seen = set()
    uniq: List[str] = []
    for t in out:
        t = t.upper()
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq or ["SPY"]
def _split_batch_df(df, tickers: List[str]) -> Dict[str, "pd.DataFrame"]:
    out: Dict[str, "pd.DataFrame"] = {}
    if df is None or getattr(df, "empty", False) or not hasattr(df, "columns"):
        return out
    if not isinstance(df.columns, pd.MultiIndex):
        if tickers:
            out[tickers[0]] = df
        return out
    fields = {"Open", "High", "Low", "Close", "Volume", "Adj Close"}
    try:
        lvl0 = list(df.columns.get_level_values(0))
        lvl1 = list(df.columns.get_level_values(1))
    except Exception:
        return out
    lvl0_is_field = any(str(x) in fields for x in lvl0)
    lvl1_is_field = any(str(x) in fields for x in lvl1)
    if (not lvl0_is_field) and lvl1_is_field:
        for t in tickers:
            try:
                out[t] = df[t]
            except Exception:
                pass
        return out
    if lvl0_is_field and (not lvl1_is_field):
        for t in tickers:
            try:
                cols = {}
                for f in ("Open", "High", "Low", "Close", "Volume"):
                    try:
                        cols[f] = df[f][t]
                    except Exception:
                        pass
                if cols:
                    out[t] = pd.DataFrame(cols)
            except Exception:
                pass
        return out
    for t in tickers:
        try:
            out[t] = df[t]
        except Exception:
            pass
    return out
def yf_download_batch(tickers: List[str], period: str, interval: str, min_rows: int, retries: int = 2) -> Dict[str, "pd.DataFrame"]:
    if yf is None or pd is None or not tickers:
        return {}
    tickers = [t.upper() for t in tickers]
    t_str = " ".join(tickers)
    last_df = None
    for i in range(max(1, retries)):
        for threads in (True, False):
            try:
                df = yf.download(
                    t_str,
                    period=period,
                    interval=interval,
                    group_by="ticker",
                    auto_adjust=False,
                    progress=False,
                    threads=threads,
                    timeout=14,
                )
                last_df = df
                out = _split_batch_df(df, tickers)
                ok = any((x is not None and not getattr(x, "empty", False) and len(x) >= min_rows) for x in out.values())
                if ok:
                    return out
            except Exception:
                pass
        time.sleep(0.6 * (2 ** i))
    try:
        return _split_batch_df(last_df, tickers) if last_df is not None else {}
    except Exception:
        return {}
def ema(series, span: int):
    try:
        return series.ewm(span=span, adjust=False).mean()
    except Exception:
        return None
def sma(series, n: int):
    try:
        return series.rolling(n).mean()
    except Exception:
        return None
def rsi14(close) -> Optional[float]:
    try:
        s = close.astype(float)
        delta = s.diff()
        up = delta.clip(lower=0).rolling(14).mean()
        down = (-delta.clip(upper=0)).rolling(14).mean()
        rs = up / (down + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        v = float(rsi.iloc[-1])
        return v if v == v else None
    except Exception:
        return None
def true_range_series(df):
    try:
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        close = df["Close"].astype(float)
        prev_close = close.shift(1)
        tr1 = (high - low).abs()
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        return tr1.combine(tr2, max).combine(tr3, max)
    except Exception:
        return None
def atr_series(df, n: int):
    tr = true_range_series(df)
    if tr is None:
        return None
    try:
        return tr.rolling(n).mean()
    except Exception:
        return None
def atr14_series(df):
    return atr_series(df, 14)
def noisy_atr(df) -> bool:
    atr = atr14_series(df)
    if atr is None:
        return False
    try:
        a = atr.dropna()
        if len(a) < 30:
            return False
        overall = float(a.mean())
        last5 = float(a.iloc[-5:].mean())
        return (overall == overall) and (last5 == last5) and (overall > 0) and (last5 > 2.0 * overall)
    except Exception:
        return False
def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)
def bb_kc_squeeze(df) -> Tuple[bool, str]:
    if df is None or getattr(df, "empty", False) or "Close" not in df.columns:
        return False, "NONE"
    try:
        close = df["Close"].astype(float)
        if len(close) < 25:
            return False, "NONE"
        mid = sma(close, 20)
        sd = close.rolling(20).std()
        if mid is None or sd is None:
            return False, "NONE"
        bb_up = mid + (2.0 * sd)
        bb_lo = mid - (2.0 * sd)
        ema20 = ema(close, 20)
        atr20 = atr_series(df, 20)
        if ema20 is None or atr20 is None:
            return False, "NONE"
        kc_up = ema20 + (1.5 * atr20)
        kc_lo = ema20 - (1.5 * atr20)
        i = -1
        squeeze_now = bool((bb_up.iloc[i] < kc_up.iloc[i]) and (bb_lo.iloc[i] > kc_lo.iloc[i]))
        squeeze_prev = bool((bb_up.iloc[i-1] < kc_up.iloc[i-1]) and (bb_lo.iloc[i-1] > kc_lo.iloc[i-1]))
        c0 = float(close.iloc[i])
        c1 = float(close.iloc[i-1])
        up0 = float(bb_up.iloc[i]); up1 = float(bb_up.iloc[i-1])
        lo0 = float(bb_lo.iloc[i]); lo1 = float(bb_lo.iloc[i-1])
        breakout = "NONE"
        if squeeze_prev:
            if (c0 > up0) and (c1 <= up1):
                breakout = "UP"
            elif (c0 < lo0) and (c1 >= lo1):
                breakout = "DOWN"
        return squeeze_now, breakout
    except Exception:
        return False, "NONE"
@dataclass
class MarketContext:
    vix: Optional[float] = None
    vix_high: bool = False
    spy_close: Optional[float] = None
    spy_ema50: Optional[float] = None
    spy_ema200: Optional[float] = None
    spy_bear: bool = False
    err: str = ""
def get_market_context() -> MarketContext:
    ctx = MarketContext()
    if yf is None or pd is None:
        ctx.err = "missing_deps"
        return ctx
    try:
        vdf = yf_download_batch(["^VIX"], period="10d", interval="1d", min_rows=2, retries=2).get("^VIX")
        if vdf is not None and not getattr(vdf, "empty", False) and "Close" in vdf.columns:
            v = float(vdf["Close"].iloc[-1])
            if v == v:
                ctx.vix = v
                ctx.vix_high = v > 30.0
    except Exception as e:
        ctx.err = (ctx.err + " | " if ctx.err else "") + "vix_err=" + safe_ascii(e)
    try:
        sdf = yf_download_batch(["SPY"], period="2y", interval="1d", min_rows=260, retries=2).get("SPY")
        if sdf is not None and not getattr(sdf, "empty", False) and "Close" in sdf.columns:
            c = sdf["Close"].astype(float)
            e50 = ema(c, 50)
            e200 = ema(c, 200)
            if e50 is not None and e200 is not None:
                sc = float(c.iloc[-1]); s50 = float(e50.iloc[-1]); s200 = float(e200.iloc[-1])
                if sc == sc and s50 == s50 and s200 == s200:
                    ctx.spy_close = sc; ctx.spy_ema50 = s50; ctx.spy_ema200 = s200
                    ctx.spy_bear = (sc < s50) and (sc < s200)
    except Exception as e:
        ctx.err = (ctx.err + " | " if ctx.err else "") + "spy_err=" + safe_ascii(e)
    return ctx
def trend_vs_ema50(df) -> Optional[str]:
    try:
        if df is None or getattr(df, "empty", False) or "Close" not in df.columns:
            return None
        close = df["Close"].astype(float)
        e50 = ema(close, 50)
        if e50 is None:
            return None
        lc = float(close.iloc[-1]); le = float(e50.iloc[-1])
        if not (lc == lc and le == le):
            return None
        return "UP" if lc > le else "DOWN"
    except Exception:
        return None
def core_signal(df) -> Tuple[str, float, str]:
    close = df["Close"].astype(float)
    efast = ema(close, 9); eslow = ema(close, 21)
    last_close = float(close.iloc[-1])
    last_efast = float(efast.iloc[-1]) if efast is not None else float("nan")
    last_eslow = float(eslow.iloc[-1]) if eslow is not None else float("nan")
    rsi_v = rsi14(close); rsi_val = float(rsi_v) if rsi_v is not None else float("nan")
    ema_diff_pct = 0.0
    if last_close == last_close and last_close != 0 and last_efast == last_efast and last_eslow == last_eslow:
        ema_diff_pct = (last_efast - last_eslow) / last_close * 100.0
    rsi_term = 0.0
    if rsi_val == rsi_val:
        rsi_term = (rsi_val - 50.0) / 8.0
    score = (ema_diff_pct * 1.8) + (rsi_term * 1.0)
    p = float(sigmoid(score)); p = max(0.0, min(1.0, p))
    bull = (last_efast == last_efast and last_eslow == last_eslow and last_efast > last_eslow and (rsi_val == rsi_val and rsi_val >= 52))
    bear = (last_efast == last_efast and last_eslow == last_eslow and last_efast < last_eslow and (rsi_val == rsi_val and rsi_val <= 48))
    strong = abs(score) >= 1.25
    if bull and not bear:
        return ("STRONG_BUY" if strong else "BUY"), p, "BUY"
    if bear and not bull:
        return ("STRONG_SELL" if strong else "SELL"), p, "SELL"
    return "HOLD", min(p, 0.55), "BUY"
def calc_sl_tp(entry: float, atr: float, side: str) -> Tuple[float, float]:
    side = (side or "").upper()
    if side == "SELL":
        return entry + (atr * 2.0), entry - (atr * 3.0)
    return entry - (atr * 2.0), entry + (atr * 3.0)
def low_rr(entry: float, atr: float, tf_label: str) -> bool:
    if not (is_finite(entry) and is_finite(atr)) or entry <= 0 or atr <= 0:
        return True
    atr_pct = atr / entry
    return atr_pct < MIN_ATR_PCT_BY_TF.get(tf_label.upper(), 0.0012)
def is_wide_market(entry: float, atr: float, tf_label: str) -> bool:
    if not (is_finite(entry) and is_finite(atr)) or entry <= 0 or atr <= 0:
        return False
    atr_pct = atr / entry
    return atr_pct >= WIDE_ATR_PCT_BY_TF.get(tf_label.upper(), 0.01)
def promote_explosive(sig: str, direction: str) -> str:
    s = (sig or "").upper()
    if direction == "UP" and "BUY" in s:
        return "EXPLOSIVE_" + s if s.startswith("STRONG_") else "EXPLOSIVE_BUY"
    if direction == "DOWN" and "SELL" in s:
        return "EXPLOSIVE_" + s if s.startswith("STRONG_") else "EXPLOSIVE_SELL"
    return sig
@dataclass
class Pred:
    ticker: str
    signal: str
    p: float
    th: float
    side: str
    reason: str
    err: str
    entry: Optional[float] = None
    atr: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    squeeze: bool = False
    breakout: str = "NONE"
    h1: str = ""
    d1: str = ""
def fmt_line(x: Pred) -> str:
    return (
        f"{x.ticker}: {x.signal} "
        f"(p={x.p:.2f}, th={x.th:.2f}, side={safe_ascii(x.side)}, reason={safe_ascii(x.reason)}, err={safe_ascii(x.err)}, "
        f"entry={fmt_num(x.entry)}, atr={fmt_num(x.atr)}, sl={fmt_num(x.sl)}, tp={fmt_num(x.tp)}, "
        f"squeeze={str(bool(x.squeeze)).lower()}, breakout={safe_ascii(x.breakout)}, "
        f"h1={safe_ascii(x.h1)}, d1={safe_ascii(x.d1)})"
    )
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="M5")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--tickers", default="")
    args = ap.parse_args()
    tf = (args.tf or "M5").upper().strip()
    if tf not in TF_MAP:
        tf = "M5"
    interval_small, period_small = TF_MAP[tf]
    th = read_threshold(default=0.55)
    tickers = (
        [t.strip().upper() for t in args.tickers.replace(",", " ").split() if t.strip()]
        if args.tickers.strip()
        else read_watchlist()
    )
    ctx = get_market_context()
    small_map = yf_download_batch(tickers, period=period_small, interval=interval_small, min_rows=80, retries=2)
    need_mta = tf in ("M5", "M15")
    h1_map: Dict[str, "pd.DataFrame"] = {}
    d1_map: Dict[str, "pd.DataFrame"] = {}
    if need_mta:
        h1_map = yf_download_batch(tickers, period="180d", interval="60m", min_rows=120, retries=2)
        d1_map = yf_download_batch(tickers, period="2y", interval="1d", min_rows=260, retries=2)
    if not args.auto:
        parts = ["[OK] multi_predict", f"TF={tf}", f"th={th:.2f}", "SQUEEZE=BB(20,2)+KC(20,1.5)", "DTSL=ATR14(2x/3x)"]
        if ctx.vix is not None:
            parts.append(f"VIX={ctx.vix:.1f}" + ("(HIGH)" if ctx.vix_high else ""))
        if ctx.spy_close is not None and ctx.spy_ema50 is not None and ctx.spy_ema200 is not None:
            parts.append(f"SPY={ctx.spy_close:.2f} EMA50={ctx.spy_ema50:.2f} EMA200={ctx.spy_ema200:.2f}" + ("(BEAR)" if ctx.spy_bear else ""))
        print(" | ".join(parts))
    for t in tickers:
        df = small_map.get(t)
        if df is None or getattr(df, "empty", False) or not all(c in df.columns for c in ("Open","High","Low","Close","Volume")):
            print(fmt_line(Pred(t, "HOLD", 0.50, th, "BUY", "data_error", "empty_or_bad_cols")))
            continue
        entry = None
        try:
            entry = float(df["Close"].astype(float).iloc[-1])
        except Exception:
            pass
        atr_last = None
        a = atr14_series(df)
        try:
            if a is not None:
                v = float(a.iloc[-1])
                atr_last = v if v == v else None
        except Exception:
            pass
        squeeze_now, breakout = bb_kc_squeeze(df)
        if ctx.vix_high:
            print(fmt_line(Pred(t, "HOLD", 0.50, th, "BUY", "vix_high", "", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout)))
            continue
        if noisy_atr(df):
            print(fmt_line(Pred(t, "HOLD", 0.50, th, "BUY", "noisy_atr", "", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout)))
            continue
        sig, p, side = core_signal(df)
        # SELL_CONF_FIX_APPLIED: for SELL signals, confidence should be 1-p
        sig_u = (sig or "").upper()
        if "SELL" in sig_u:
            try:
                p = 1.0 - float(p)
            except Exception:
                pass

        if ctx.spy_bear and ("BUY" in sig):
            print(fmt_line(Pred(t, "HOLD", float(p), th, side, "spy_bear", "", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout)))
            continue
        if ("BUY" in sig or "SELL" in sig) and float(p) < float(th):
            print(fmt_line(Pred(t, "HOLD", float(p), th, side, "low_proba", "", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout)))
            continue
        # DTSL + RR
        sl = tp = None
        if ("BUY" in sig or "SELL" in sig) and is_finite(entry) and is_finite(atr_last) and float(atr_last) > 0:
            sl, tp = calc_sl_tp(float(entry), float(atr_last), side)
            if low_rr(float(entry), float(atr_last), tf):
                print(fmt_line(Pred(t, "HOLD", float(p), th, side, "low_rr", "", entry=entry, atr=atr_last, sl=sl, tp=tp, squeeze=squeeze_now, breakout=breakout)))
                continue
        elif ("BUY" in sig or "SELL" in sig):
            print(fmt_line(Pred(t, "HOLD", float(p), th, side, "data_error", "atr_na", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout)))
            continue
        # wide market stricter if no squeeze/breakout
        if ("BUY" in sig or "SELL" in sig) and is_finite(entry) and is_finite(atr_last):
            if is_wide_market(float(entry), float(atr_last), tf) and (not squeeze_now) and (breakout == "NONE"):
                hard_th = float(th) + 0.08
                if (not sig.startswith("STRONG_")) and float(p) < hard_th:
                    print(fmt_line(Pred(t, "HOLD", float(p), th, side, "wide_market", "", entry=entry, atr=atr_last, sl=sl, tp=tp, squeeze=squeeze_now, breakout=breakout)))
                    continue
        # EXPLOSIVE if breakout aligns with signal
        if breakout in ("UP","DOWN") and (("BUY" in sig and breakout=="UP") or ("SELL" in sig and breakout=="DOWN")):
            sig = promote_explosive(sig, breakout)
            reason = "squeeze_breakout"
        else:
            reason = "ok" if ("BUY" in sig or "SELL" in sig) else "model_hold"
        # MTA (M5/M15)
        h1_tr = d1_tr = ""
        if need_mta and ("BUY" in sig or "SELL" in sig):
            h1_tr = trend_vs_ema50(h1_map.get(t)) or "NA"
            d1_tr = trend_vs_ema50(d1_map.get(t)) or "NA"
            if "BUY" in sig and (h1_tr=="DOWN" and d1_tr=="DOWN"):
                print(fmt_line(Pred(t, "HOLD", float(p), th, side, "trend_conflict", "", entry=entry, atr=atr_last, sl=sl, tp=tp, squeeze=squeeze_now, breakout=breakout, h1=h1_tr, d1=d1_tr)))
                continue
            if "SELL" in sig and (h1_tr=="UP" and d1_tr=="UP"):
                print(fmt_line(Pred(t, "HOLD", float(p), th, side, "trend_conflict", "", entry=entry, atr=atr_last, sl=sl, tp=tp, squeeze=squeeze_now, breakout=breakout, h1=h1_tr, d1=d1_tr)))
                continue
        print(fmt_line(Pred(t, sig, float(p), th, side, reason, "", entry=entry, atr=atr_last, sl=sl, tp=tp, squeeze=squeeze_now, breakout=breakout, h1=h1_tr, d1=d1_tr)))
if __name__ == "__main__":
    main()
