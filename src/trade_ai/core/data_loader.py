from __future__ import annotations

import contextlib
import io
import re
import threading
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
from trade_ai.utils.logger import setup_logger

TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,15}$")
logger = setup_logger("trade_ai.data_loader")
YF_DOWNLOAD_LOCK = threading.RLock()


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
        keep_cols = [col for col in ("Open", "High", "Low", "Close", "Volume", "Adj Close") if col in out.columns]
        if keep_cols:
            out = out.dropna(how="all", subset=keep_cols)
        if "Close" in out.columns:
            out = out[out["Close"].notna()]
        return out
    except Exception:
        return df


def usable_df(df, min_rows: int) -> bool:
    return df is not None and not getattr(df, "empty", False) and len(df) >= min_rows


def _download_interval(interval: str) -> str:
    normalized = (interval or "").strip().lower()
    if normalized == "4h":
        return "60m"
    return normalized


def resample_ohlcv_df(df, interval: str):
    if pd is None or df is None or getattr(df, "empty", False):
        return df
    normalized = (interval or "").strip().lower()
    if normalized != "4h":
        return df
    if not getattr(df.index, "inferred_type", "").startswith("datetime"):
        return df
    agg_map = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
        "Adj Close": "last",
    }
    try:
        available = {column: rule for column, rule in agg_map.items() if column in df.columns}
        if not available:
            return df
        out = df.sort_index().resample("4h").agg(available).dropna(subset=["Close"])
        return out if not out.empty else df
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
    except Exception as exc:
        logger.error("[%s] cache read failed: %s", ticker, exc)
        return None
    if df is None or getattr(df, "empty", False) or len(df) < min_rows:
        return None
    return df


def yf_download_safe(ticker: str, period: str, interval: str, min_rows: int = settings.YF_ENTRY_MIN_ROWS, retries: int = settings.YF_RETRIES):
    request_interval = _download_interval(interval)
    if yf is None:
        cached = load_cached_df(ticker, period, interval, min_rows=min_rows)
        if cached is not None:
            logger.warning("[%s] data=CACHE_ONLY source=cache", ticker)
        else:
            logger.error("[%s] data=FAIL source=no_yfinance", ticker)
        return cached
    last_df = None
    for attempt in range(max(1, retries)):
        try:
            with YF_DOWNLOAD_LOCK:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    df = yf.download(
                        ticker,
                        period=period,
                        interval=request_interval,
                        progress=False,
                        threads=False,
                        timeout=settings.YF_SINGLE_TIMEOUT_SEC,
                        auto_adjust=False,
                        group_by="column",
                    )
        except Exception as exc:
            logger.warning("[%s] download attempt=%d/%d failed: %s", ticker, attempt + 1, max(1, retries), exc)
            df = None
        df = normalize_ohlcv_df(df)
        df = resample_ohlcv_df(df, interval)
        if usable_df(df, min_rows):
            save_cached_df(ticker, period, interval, df)
            logger.info("[%s] data=OK source=yfinance rows=%d", ticker, len(df))
            return df
        logger.warning("[%s] data=EMPTY attempt=%d/%d", ticker, attempt + 1, max(1, retries))
        last_df = df
        time.sleep(1.0 * (2 ** attempt))
    cached = load_cached_df(ticker, period, interval, min_rows=min_rows)
    if cached is not None:
        logger.warning("[%s] data=OK source=cache rows=%d", ticker, len(cached))
        return cached
    logger.error("[%s] data=FAIL source=unavailable", ticker)
    return None


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
    request_interval = _download_interval(interval)
    if yf is None or pd is None or not tickers:
        out = {
            ticker: cached
            for ticker in tickers
            for cached in [load_cached_df(ticker, period, interval, min_rows=min_rows)]
            if cached is not None
        }
        for ticker in tickers:
            if ticker not in out:
                logger.error("[%s] data=FAIL source=no_deps", ticker)
        return out
    last_df = None
    joined = " ".join(tickers)
    for attempt in range(max(1, retries)):
        for threads in (True, False):
            try:
                with YF_DOWNLOAD_LOCK:
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        df = yf.download(
                            joined,
                            period=period,
                            interval=request_interval,
                            group_by="ticker",
                            auto_adjust=False,
                            progress=False,
                            threads=threads,
                            timeout=settings.YF_BATCH_TIMEOUT_SEC,
                        )
            except Exception as exc:
                logger.warning(
                    "[batch:%s] attempt=%d/%d threads=%s failed: %s",
                    joined,
                    attempt + 1,
                    max(1, retries),
                    threads,
                    exc,
                )
                continue
            last_df = df
            out = {
                ticker: resample_ohlcv_df(item, interval)
                for ticker, item in _split_batch_df(df, tickers).items()
            }
            for ticker, item in list(out.items()):
                if usable_df(item, min_rows):
                    save_cached_df(ticker, period, interval, item)
            if any(usable_df(item, min_rows) for item in out.values()):
                for ticker in tickers:
                    if ticker not in out or not usable_df(out[ticker], min_rows):
                        cached = load_cached_df(ticker, period, interval, min_rows=min_rows)
                        if cached is not None:
                            out[ticker] = cached
                for ticker in tickers:
                    if ticker in out and usable_df(out.get(ticker), min_rows):
                        logger.info("[%s] data=OK source=batch rows=%d", ticker, len(out[ticker]))
                    else:
                        logger.warning("[%s] data=PARTIAL source=batch", ticker)
                return out
        time.sleep(0.6 * (2 ** attempt))

    out = _split_batch_df(last_df, tickers) if last_df is not None else {}
    for ticker in tickers:
        if ticker not in out or not usable_df(out.get(ticker), min_rows):
            single_df = yf_download_safe(ticker, period=period, interval=interval, min_rows=min_rows, retries=settings.YF_RETRIES)
            if usable_df(single_df, min_rows):
                out[ticker] = single_df
    for ticker in tickers:
        if ticker in out and usable_df(out.get(ticker), min_rows):
            logger.info("[%s] data=OK source=final rows=%d", ticker, len(out[ticker]))
        else:
            logger.error("[%s] data=FAIL source=batch_fallback", ticker)
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
