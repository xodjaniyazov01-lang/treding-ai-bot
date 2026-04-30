from __future__ import annotations
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
