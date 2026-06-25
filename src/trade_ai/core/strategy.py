from __future__ import annotations

import math
from functools import lru_cache
from dataclasses import dataclass
import logging
from typing import Dict, List, Optional, Tuple

import joblib
import pandas as pd

from trade_ai.config import settings
from trade_ai.core.data_loader import read_watchlist, yf_download_batch
from trade_ai.utils.helpers import clamp, fmt_num, is_finite, safe_ascii

logger = logging.getLogger("trade_ai.strategy")


@dataclass
class MarketContext:
    vix: Optional[float] = None
    vix_high: bool = False
    spy_close: Optional[float] = None
    spy_ema50: Optional[float] = None
    spy_ema200: Optional[float] = None
    spy_bear: bool = False
    err: str = ""


@dataclass
class Prediction:
    ticker: str
    signal: str
    p: float
    threshold: float
    side: str
    reason: str
    err: str = ""
    entry: Optional[float] = None
    atr: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    squeeze: bool = False
    breakout: str = "NONE"
    h1: str = ""
    d1: str = ""
    features: Optional[dict] = None


MIN_ATR_PCT_BY_TF = {
    "M5": 0.0009,
    "M15": 0.0011,
    "H1": 0.0016,
    "H4": 0.0022,
}

WIDE_ATR_PCT_BY_TF = {
    "M5": 0.0060,
    "M15": 0.0080,
    "H1": 0.0120,
    "H4": 0.0180,
}


@lru_cache(maxsize=1)
def load_prediction_model():
    model = joblib.load(settings.MODEL_PATH)
    logger.info(
        "MODEL loaded path=%s type=%s",
        settings.MODEL_PATH,
        type(model).__name__,
    )
    return model


def get_model_status() -> dict:
    path = settings.MODEL_PATH
    status = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "loaded": False,
        "model_type": "",
        "error": "",
    }
    try:
        model = load_prediction_model()
        status["loaded"] = True
        status["model_type"] = type(model).__name__
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {safe_ascii(exc)}"
    return status


def read_threshold(default: float = settings.DEFAULT_THRESHOLD) -> float:
    try:
        raw = settings.THRESHOLD_PATH.read_text(encoding="utf-8", errors="ignore").replace("\ufeff", "").strip()
        return clamp(float(raw), settings.THRESHOLD_MIN, settings.THRESHOLD_MAX)
    except Exception:
        return default


def ema(series, span: int):
    try:
        return series.ewm(span=span, adjust=False).mean()
    except Exception:
        return None


def sma(series, window: int):
    try:
        return series.rolling(window).mean()
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
        value = float(rsi.iloc[-1])
        return value if value == value else None
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


def atr_series(df, window: int):
    tr = true_range_series(df)
    if tr is None:
        return None
    try:
        return tr.rolling(window).mean()
    except Exception:
        return None


def atr14_series(df):
    return atr_series(df, 14)


def noisy_atr(df) -> bool:
    atr = atr14_series(df)
    if atr is None:
        return False
    try:
        values = atr.dropna()
        if len(values) < 30:
            return False
        overall = float(values.mean())
        last5 = float(values.iloc[-5:].mean())
        return overall > 0 and last5 > 2.0 * overall
    except Exception:
        return False


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
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
        ema20 = ema(close, 20)
        atr20 = atr_series(df, 20)
        if mid is None or sd is None or ema20 is None or atr20 is None:
            return False, "NONE"
        bb_up = mid + (2.0 * sd)
        bb_lo = mid - (2.0 * sd)
        kc_up = ema20 + (1.5 * atr20)
        kc_lo = ema20 - (1.5 * atr20)
        squeeze_prev = bool((bb_up.iloc[-2] < kc_up.iloc[-2]) and (bb_lo.iloc[-2] > kc_lo.iloc[-2]))
        squeeze_now = bool((bb_up.iloc[-1] < kc_up.iloc[-1]) and (bb_lo.iloc[-1] > kc_lo.iloc[-1]))
        c0 = float(close.iloc[-1])
        c1 = float(close.iloc[-2])
        up0 = float(bb_up.iloc[-1])
        up1 = float(bb_up.iloc[-2])
        lo0 = float(bb_lo.iloc[-1])
        lo1 = float(bb_lo.iloc[-2])
        breakout = "NONE"
        if squeeze_prev:
            if c0 > up0 and c1 <= up1:
                breakout = "UP"
            elif c0 < lo0 and c1 >= lo1:
                breakout = "DOWN"
        return squeeze_now, breakout
    except Exception:
        return False, "NONE"


def get_market_context() -> MarketContext:
    ctx = MarketContext()
    try:
        vdf = yf_download_batch(["^VIX"], period="10d", interval="1d", min_rows=2, retries=2).get("^VIX")
        if vdf is not None and not getattr(vdf, "empty", False) and "Close" in vdf.columns:
            vix = float(vdf["Close"].iloc[-1])
            if vix == vix:
                ctx.vix = vix
                ctx.vix_high = vix > settings.VIX_HIGH_THRESHOLD
        else:
            ctx.err = "vix_missing"
    except Exception as exc:
        ctx.err = f"vix_err={safe_ascii(exc)}"
    try:
        sdf = yf_download_batch(["SPY"], period="2y", interval="1d", min_rows=settings.YF_DAILY_MIN_ROWS, retries=2).get("SPY")
        if sdf is not None and not getattr(sdf, "empty", False) and "Close" in sdf.columns:
            close = sdf["Close"].astype(float)
            ema50 = ema(close, 50)
            ema200 = ema(close, 200)
            if ema50 is not None and ema200 is not None:
                spy_close = float(close.iloc[-1])
                spy_ema50 = float(ema50.iloc[-1])
                spy_ema200 = float(ema200.iloc[-1])
                if spy_close == spy_close and spy_ema50 == spy_ema50 and spy_ema200 == spy_ema200:
                    ctx.spy_close = spy_close
                    ctx.spy_ema50 = spy_ema50
                    ctx.spy_ema200 = spy_ema200
                    ctx.spy_bear = (spy_close < spy_ema50) and (spy_close < spy_ema200)
        else:
            suffix = "spy_missing"
            ctx.err = f"{ctx.err} | {suffix}" if ctx.err else suffix
    except Exception as exc:
        suffix = f"spy_err={safe_ascii(exc)}"
        ctx.err = f"{ctx.err} | {suffix}" if ctx.err else suffix
    return ctx


def trend_vs_ema50(df) -> Optional[str]:
    if df is None or getattr(df, "empty", False) or "Close" not in df.columns:
        return None
    try:
        close = df["Close"].astype(float)
        ema50 = ema(close, 50)
        if ema50 is None:
            return None
        last_close = float(close.iloc[-1])
        last_ema = float(ema50.iloc[-1])
        if last_close != last_close or last_ema != last_ema:
            return None
        return "UP" if last_close > last_ema else "DOWN"
    except Exception:
        return None


def infer_side(df) -> Tuple[str, str]:
    close = df["Close"].astype(float)
    fast = ema(close, 9)
    slow = ema(close, 21)
    last_fast = float(fast.iloc[-1]) if fast is not None else float("nan")
    last_slow = float(slow.iloc[-1]) if slow is not None else float("nan")
    rsi_value = rsi14(close)
    rsi_num = float(rsi_value) if rsi_value is not None else float("nan")
    if last_fast == last_fast and last_slow == last_slow and last_fast > last_slow and rsi_num == rsi_num and rsi_num >= 52:
        return "BUY", "trend_bull"
    if last_fast == last_fast and last_slow == last_slow and last_fast < last_slow and rsi_num == rsi_num and rsi_num <= 48:
        return "SELL", "trend_bear"
    return "BUY", "trend_flat"


def detect_volume_spike(df) -> int:
    try:
        volume = df["Volume"].astype(float)
        if len(volume) < 20:
            return 0
        current = float(volume.iloc[-1])
        base = float(volume.rolling(20).mean().iloc[-2])
        if base <= 0:
            return 0
        return int(current > (base * 1.5))
    except Exception:
        return 0


def detect_pattern_name(side: str, squeeze_now: bool, breakout: str, is_consolidation: int, trend_align: int) -> str:
    side = (side or "").upper()
    if side == "BUY":
        if breakout == "UP" and squeeze_now:
            return "bull_pennant"
        if breakout == "UP":
            return "bull_flag"
        if is_consolidation:
            return "range_breakout"
        if trend_align:
            return "ascending_triangle"
        return "double_bottom"
    if breakout == "DOWN" and squeeze_now:
        return "bear_pennant"
    if breakout == "DOWN":
        return "head_shoulders"
    if is_consolidation:
        return "range_breakout"
    if trend_align:
        return "descending_triangle"
    return "double_top"


def build_feature_row(df_small, df_h1, df_d1, squeeze_now: bool, breakout: str) -> dict:
    close = df_small["Close"].astype(float)
    last_close = float(close.iloc[-1])
    ema20 = ema(close, 20)
    close_vs_ema = int(ema20 is not None and float(ema20.iloc[-1]) == float(ema20.iloc[-1]) and last_close > float(ema20.iloc[-1]))
    rsi_value = rsi14(close)
    rsi_num = float(rsi_value) if rsi_value is not None else 50.0
    atr_data = atr14_series(df_small)
    atr_last = None
    if atr_data is not None:
        try:
            atr_last = float(atr_data.iloc[-1])
        except Exception:
            atr_last = None
    atr_ratio = float(atr_last / last_close) if is_finite(atr_last) and is_finite(last_close) and last_close > 0 else 0.0
    st_3m = 1 if (trend_vs_ema50(df_small) or "DOWN") == "UP" else 0
    st_1h = 1 if (trend_vs_ema50(df_h1) or "DOWN") == "UP" else 0
    st_4h = 1 if (trend_vs_ema50(df_d1) or "DOWN") == "UP" else 0
    trend_align = int(st_1h == st_4h)
    is_consolidation = int(atr_ratio < 0.0025)
    side, _ = infer_side(df_small)
    pattern_name = detect_pattern_name(side, squeeze_now, breakout, is_consolidation, trend_align)
    return {
        "pattern_name": pattern_name,
        "side": side,
        "st_3m": st_3m,
        "st_1h": st_1h,
        "st_4h": st_4h,
        "trend_align": trend_align,
        "is_consolidation": is_consolidation,
        "breakout": int(breakout in ("UP", "DOWN")),
        "volume_spike": detect_volume_spike(df_small),
        "neckline_break": int(breakout in ("UP", "DOWN")),
        "atr_ratio": atr_ratio,
        "rsi": rsi_num if rsi_num == rsi_num else 50.0,
        "close_vs_ema": close_vs_ema,
    }


def core_signal(feature_row: dict) -> Tuple[str, float, str]:
    model = load_prediction_model()
    feature_frame = pd.DataFrame([feature_row], columns=settings.PATTERN_FEATURES)
    proba = float(model.predict_proba(feature_frame)[0][1])
    side = str(feature_row["side"]).upper()
    strong_threshold = max(0.85, read_threshold() + 0.15)
    if proba >= strong_threshold:
        return (f"STRONG_{side}", proba, side)
    if proba >= read_threshold():
        return side, proba, side
    return "HOLD", proba, side


def calc_sl_tp(entry: float, atr: float, side: str) -> Tuple[float, float]:
    if (side or "").upper() == "SELL":
        return entry + (atr * 2.0), entry - (atr * 3.0)
    return entry - (atr * 2.0), entry + (atr * 3.0)


def low_rr(entry: float, atr: float, tf_label: str) -> bool:
    if not (is_finite(entry) and is_finite(atr)) or entry <= 0 or atr <= 0:
        return True
    return (atr / entry) < MIN_ATR_PCT_BY_TF.get(tf_label.upper(), 0.0012)


def is_wide_market(entry: float, atr: float, tf_label: str) -> bool:
    if not (is_finite(entry) and is_finite(atr)) or entry <= 0 or atr <= 0:
        return False
    return (atr / entry) >= WIDE_ATR_PCT_BY_TF.get(tf_label.upper(), 0.01)


def promote_explosive(signal: str, direction: str) -> str:
    upper = (signal or "").upper()
    if direction == "UP" and "BUY" in upper:
        return "EXPLOSIVE_" + upper if upper.startswith("STRONG_") else "EXPLOSIVE_BUY"
    if direction == "DOWN" and "SELL" in upper:
        return "EXPLOSIVE_" + upper if upper.startswith("STRONG_") else "EXPLOSIVE_SELL"
    return signal


def format_prediction(prediction: Prediction) -> str:
    return (
        f"{prediction.ticker}: {prediction.signal} "
        f"(p={prediction.p:.2f}, th={prediction.threshold:.2f}, side={safe_ascii(prediction.side)}, "
        f"reason={safe_ascii(prediction.reason)}, err={safe_ascii(prediction.err)}, "
        f"entry={fmt_num(prediction.entry)}, atr={fmt_num(prediction.atr)}, "
        f"sl={fmt_num(prediction.sl)}, tp={fmt_num(prediction.tp)}, "
        f"squeeze={str(bool(prediction.squeeze)).lower()}, breakout={safe_ascii(prediction.breakout)}, "
        f"h1={safe_ascii(prediction.h1)}, d1={safe_ascii(prediction.d1)})"
    )


def test_log_line(prediction: Prediction) -> str:
    return (
        f"[CHECK] {prediction.ticker} | p={prediction.p:.2f} | threshold={prediction.threshold:.2f} | "
        f"signal={prediction.signal} | reason={prediction.reason} | err={prediction.err or '-'}"
    )


def predict_market(tf_label: str, tickers: Optional[List[str]] = None) -> List[Prediction]:
    tf = (tf_label or settings.DEFAULT_TF_LABEL).upper().strip()
    if tf not in settings.TF_MAP:
        tf = settings.DEFAULT_TF_LABEL
    interval_small, period_small = settings.TF_MAP[tf]
    threshold = read_threshold()
    tickers = tickers or read_watchlist()
    ctx = get_market_context()
    small_map = yf_download_batch(tickers, period=period_small, interval=interval_small, min_rows=settings.YF_SIGNAL_MIN_ROWS, retries=2)

    need_mta = tf in ("M5", "M15")
    h1_map: Dict[str, object] = {}
    d1_map: Dict[str, object] = {}
    if need_mta:
        h1_map = yf_download_batch(tickers, period="180d", interval="60m", min_rows=settings.YF_TREND_MIN_ROWS, retries=2)
        d1_map = yf_download_batch(tickers, period="2y", interval="1d", min_rows=settings.YF_DAILY_MIN_ROWS, retries=2)

    predictions: List[Prediction] = []
    for ticker in tickers:
        df_small = small_map.get(ticker)
        if df_small is None or getattr(df_small, "empty", False):
            predictions.append(Prediction(ticker=ticker, signal="HOLD", p=0.50, threshold=threshold, side="BUY", reason="data_error", err="empty_small"))
            continue
        if not all(col in df_small.columns for col in ("Open", "High", "Low", "Close", "Volume")):
            predictions.append(Prediction(ticker=ticker, signal="HOLD", p=0.50, threshold=threshold, side="BUY", reason="data_error", err="bad_small_cols"))
            continue

        try:
            entry = float(df_small["Close"].astype(float).iloc[-1])
        except Exception:
            entry = None
        atr_data = atr14_series(df_small)
        atr_last = None
        try:
            if atr_data is not None:
                value = float(atr_data.iloc[-1])
                atr_last = value if value == value else None
        except Exception:
            atr_last = None

        squeeze_now, breakout = bb_kc_squeeze(df_small)
        if ctx.vix_high:
            predictions.append(Prediction(ticker, "HOLD", 0.50, threshold, "BUY", "vix_high", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout))
            continue
        if noisy_atr(df_small):
            predictions.append(Prediction(ticker, "HOLD", 0.50, threshold, "BUY", "noisy_atr", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout))
            continue

        try:
            feature_row = build_feature_row(
                df_small=df_small,
                df_h1=h1_map.get(ticker),
                df_d1=d1_map.get(ticker),
                squeeze_now=squeeze_now,
                breakout=breakout,
            )
            signal, proba, side = core_signal(feature_row)
        except Exception as exc:
            predictions.append(Prediction(ticker, "HOLD", 0.50, threshold, "BUY", "model_error", safe_ascii(type(exc).__name__), entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout))
            continue

        if ctx.spy_bear and "BUY" in signal:
            predictions.append(Prediction(ticker, "HOLD", float(proba), threshold, side, "spy_bear", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout))
            continue
        bypass_threshold = settings.TEST_MODE and settings.IGNORE_THRESHOLD_IN_TEST
        if ("BUY" in signal or "SELL" in signal) and (not bypass_threshold) and float(proba) < threshold:
            predictions.append(Prediction(ticker, "HOLD", float(proba), threshold, side, "low_proba", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout))
            continue

        sl = tp = None
        if ("BUY" in signal or "SELL" in signal) and is_finite(entry) and is_finite(atr_last) and float(atr_last) > 0:
            sl, tp = calc_sl_tp(float(entry), float(atr_last), side)
            if low_rr(float(entry), float(atr_last), tf):
                predictions.append(Prediction(ticker, "HOLD", float(proba), threshold, side, "low_rr", entry=entry, atr=atr_last, sl=sl, tp=tp, squeeze=squeeze_now, breakout=breakout))
                continue
        elif "BUY" in signal or "SELL" in signal:
            predictions.append(Prediction(ticker, "HOLD", float(proba), threshold, side, "data_error", "atr_na", entry=entry, atr=atr_last, squeeze=squeeze_now, breakout=breakout))
            continue

        if ("BUY" in signal or "SELL" in signal) and is_finite(entry) and is_finite(atr_last):
            hard_threshold = threshold + 0.08
            if is_wide_market(float(entry), float(atr_last), tf) and (not squeeze_now) and breakout == "NONE":
                if (not signal.startswith("STRONG_")) and (not bypass_threshold) and float(proba) < hard_threshold:
                    predictions.append(Prediction(ticker, "HOLD", float(proba), threshold, side, "wide_market", entry=entry, atr=atr_last, sl=sl, tp=tp, squeeze=squeeze_now, breakout=breakout))
                    continue

        promoted = False
        if breakout in ("UP", "DOWN"):
            if (breakout == "UP" and "BUY" in signal) or (breakout == "DOWN" and "SELL" in signal):
                signal = promote_explosive(signal, breakout)
                promoted = True

        h1_tr = ""
        d1_tr = ""
        if need_mta and ("BUY" in signal or "SELL" in signal):
            h1_tr = trend_vs_ema50(h1_map.get(ticker)) or "NA"
            d1_tr = trend_vs_ema50(d1_map.get(ticker)) or "NA"
            if "BUY" in signal and h1_tr == "DOWN" and d1_tr == "DOWN":
                predictions.append(Prediction(ticker, "HOLD", float(proba), threshold, side, "trend_conflict", entry=entry, atr=atr_last, sl=sl, tp=tp, squeeze=squeeze_now, breakout=breakout, h1=h1_tr, d1=d1_tr))
                continue
            if "SELL" in signal and h1_tr == "UP" and d1_tr == "UP":
                predictions.append(Prediction(ticker, "HOLD", float(proba), threshold, side, "trend_conflict", entry=entry, atr=atr_last, sl=sl, tp=tp, squeeze=squeeze_now, breakout=breakout, h1=h1_tr, d1=d1_tr))
                continue
            s_tr = trend_vs_ema50(df_small) or "NA"
            if "BUY" in signal and s_tr == "UP" and h1_tr == "UP" and d1_tr == "UP":
                signal = "EXPLOSIVE_STRONG_BUY" if signal.startswith("EXPLOSIVE_") else "STRONG_BUY"
            if "SELL" in signal and s_tr == "DOWN" and h1_tr == "DOWN" and d1_tr == "DOWN":
                signal = "EXPLOSIVE_STRONG_SELL" if signal.startswith("EXPLOSIVE_") else "STRONG_SELL"

        reason = "squeeze_breakout" if promoted else ("ok" if ("BUY" in signal or "SELL" in signal) else "model_hold")
        predictions.append(
            Prediction(
                ticker=ticker,
                signal=signal,
                p=float(proba),
                threshold=threshold,
                side=side,
                reason=reason,
                entry=entry,
                atr=atr_last,
                sl=sl,
                tp=tp,
                squeeze=squeeze_now,
                breakout=breakout,
                h1=h1_tr,
                d1=d1_tr,
                features=feature_row,
            )
        )
    return predictions
