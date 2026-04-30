from __future__ import annotations

import contextlib
import io
import re
import time
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

from trade_ai.config import settings

TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,15}$")


def normalize_tickers(items: List[str]) -> List[str]:
    seen = set()
    tickers: List[str] = []
    for item in items:
        ticker = (item or "").strip().upper()
        if not ticker or not TICKER_RE.match(ticker) or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers or ["SPY"]


def read_watchlist(path: Path = settings.WATCHLIST_PATH) -> List[str]:
    if not path.exists():
        return ["SPY"]
    raw = path.read_text(encoding="utf-8", errors="ignore")
    tokens: List[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens.extend(part.strip() for part in line.replace(",", " ").split())
    return normalize_tickers(tokens)


def cache_path(ticker: str, period: str, interval: str) -> Path:
    safe_ticker = re.sub(r"[^A-Z0-9._-]+", "_", (ticker or "").upper())
    return settings.YF_CACHE_DIR / f"{safe_ticker}_{period}_{interval}.csv"


def normalize_ohlcv_df(df):
    if df is None:
        return None
    try:
        out = df.copy()
        if hasattr(out.columns, "nlevels") and out.columns.nlevels > 1:
            out.columns = [col[0] for col in out.columns]
        return out
    except Exception:
        return df


def save_cached_df(ticker: str, period: str, interval: str, df) -> None:
    if df is None or getattr(df, "empty", False):
        return
    keep_cols = [col for col in ("Open", "High", "Low", "Close", "Volume", "Adj Close") if col in df.columns]
    if not keep_cols:
        return
    settings.YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df[keep_cols].to_csv(cache_path(ticker, period, interval), encoding="utf-8")


def load_cached_df(ticker: str, period: str, interval: str, min_rows: int = 1):
    if pd is None:
        return None
    path = cache_path(ticker, period, interval)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return None
    if df is None or getattr(df, "empty", False) or len(df) < min_rows:
        return None
    return df


def yf_download_safe(ticker: str, period: str, interval: str, min_rows: int = settings.YF_ENTRY_MIN_ROWS, retries: int = settings.YF_RETRIES):
    if yf is None:
        return load_cached_df(ticker, period, interval, min_rows=min_rows)
    last_df = None
    for attempt in range(max(1, retries)):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                df = yf.download(
                    ticker,
                    period=period,
                    interval=interval,
                    progress=False,
                    threads=False,
                    timeout=settings.YF_SINGLE_TIMEOUT_SEC,
                    auto_adjust=False,
                    group_by="column",
                )
        except Exception:
            df = None
        df = normalize_ohlcv_df(df)
        if df is not None and not getattr(df, "empty", False) and len(df) >= min_rows:
            save_cached_df(ticker, period, interval, df)
            return df
        last_df = df
        time.sleep(1.0 * (2 ** attempt))
    cached = load_cached_df(ticker, period, interval, min_rows=min_rows)
    if cached is not None:
        return cached
    return normalize_ohlcv_df(last_df)


def _split_batch_df(df, tickers: List[str]) -> Dict[str, "pd.DataFrame"]:
    out: Dict[str, "pd.DataFrame"] = {}
    if pd is None or df is None or getattr(df, "empty", False) or not hasattr(df, "columns"):
        return out
    if not isinstance(df.columns, pd.MultiIndex):
        if tickers:
            out[tickers[0]] = normalize_ohlcv_df(df)
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
        for ticker in tickers:
            try:
                out[ticker] = normalize_ohlcv_df(df[ticker])
            except Exception:
                continue
        return out

    if lvl0_is_field and (not lvl1_is_field):
        for ticker in tickers:
            try:
                cols = {}
                for field in ("Open", "High", "Low", "Close", "Volume"):
                    try:
                        cols[field] = df[field][ticker]
                    except Exception:
                        pass
                if cols:
                    out[ticker] = pd.DataFrame(cols)
            except Exception:
                continue
        return out

    for ticker in tickers:
        try:
            out[ticker] = normalize_ohlcv_df(df[ticker])
        except Exception:
            continue
    return out


def yf_download_batch(tickers: List[str], period: str, interval: str, min_rows: int, retries: int = 2) -> Dict[str, "pd.DataFrame"]:
    tickers = normalize_tickers(tickers)
    if yf is None or pd is None or not tickers:
        return {
            ticker: cached
            for ticker in tickers
            for cached in [load_cached_df(ticker, period, interval, min_rows=min_rows)]
            if cached is not None
        }
    last_df = None
    joined = " ".join(tickers)
    for attempt in range(max(1, retries)):
        for threads in (True, False):
            try:
                df = yf.download(
                    joined,
                    period=period,
                    interval=interval,
                    group_by="ticker",
                    auto_adjust=False,
                    progress=False,
                    threads=threads,
                    timeout=settings.YF_BATCH_TIMEOUT_SEC,
                )
            except Exception:
                continue
            last_df = df
            out = _split_batch_df(df, tickers)
            for ticker, item in list(out.items()):
                if item is not None and not getattr(item, "empty", False) and len(item) >= min_rows:
                    save_cached_df(ticker, period, interval, item)
            if any(item is not None and not getattr(item, "empty", False) and len(item) >= min_rows for item in out.values()):
                for ticker in tickers:
                    if ticker not in out or out[ticker] is None or getattr(out[ticker], "empty", False) or len(out[ticker]) < min_rows:
                        cached = load_cached_df(ticker, period, interval, min_rows=min_rows)
                        if cached is not None:
                            out[ticker] = cached
                return out
        time.sleep(0.6 * (2 ** attempt))

    out = _split_batch_df(last_df, tickers) if last_df is not None else {}
    for ticker in tickers:
        if ticker not in out or out[ticker] is None or getattr(out[ticker], "empty", False) or len(out[ticker]) < min_rows:
            single_df = yf_download_safe(ticker, period=period, interval=interval, min_rows=min_rows, retries=settings.YF_RETRIES)
            if single_df is not None and not getattr(single_df, "empty", False) and len(single_df) >= min_rows:
                out[ticker] = single_df
    return out


def rsi14_from_close(close) -> Optional[float]:
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


def fetch_entry_atr_rsi(ticker: str, interval: str, period: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    df = yf_download_safe(ticker, period=period, interval=interval, min_rows=settings.YF_ENTRY_MIN_ROWS, retries=settings.YF_RETRIES)
    if df is None or getattr(df, "empty", False) or len(df) < settings.YF_ENTRY_MIN_ROWS:
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
    return entry, atr14, rsi14_from_close(close)
