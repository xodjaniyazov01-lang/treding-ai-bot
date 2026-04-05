from __future__ import annotations
from pathlib import Path
from datetime import datetime
import re
ROOT = Path.cwd()
WB = ROOT / "src" / "trade_ai" / "app" / "watch_best.py"
MP = ROOT / "src" / "trade_ai" / "legacy" / "multi_predict.py"
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
def backup(p: Path):
    b = p.with_suffix(p.suffix + f".bak_{stamp}")
    b.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[backup] {p} -> {b}")
def insert_block(s: str, block: str, markers: list[str]) -> str:
    if block.strip() in s:
        return s
    for m in markers:
        i = s.find(m)
        if i != -1:
            return s[:i] + block + "\n\n" + s[i:]
    # fallback: after imports (first double newline)
    m = re.search(r"\n\s*\n", s)
    if m:
        j = m.end()
        return s[:j] + block + "\n\n" + s[j:]
    return block + "\n\n" + s
def ensure_import(s: str, imp_line: str) -> str:
    if re.search(r"^" + re.escape(imp_line) + r"\s*$", s, flags=re.M):
        return s
    # insert after last import line
    lines = s.splitlines()
    last_import_idx = -1
    for idx, ln in enumerate(lines[:200]):  # imports are near top
        if ln.startswith("import ") or ln.startswith("from "):
            last_import_idx = idx
    if last_import_idx >= 0:
        lines.insert(last_import_idx + 1, imp_line)
        return "\n".join(lines) + ("\n" if s.endswith("\n") else "")
    return imp_line + "\n" + s
# ---------- Patch watch_best.py ----------
def patch_watch_best():
    if not WB.exists():
        raise SystemExit(f"watch_best.py topilmadi: {WB}")
    backup(WB)
    s = WB.read_text(encoding="utf-8")
    # imports needed for verbose tech snapshot
    s = ensure_import(s, "import os")
    verbose_block = r'''
# ================== VERBOSE / DIAGNOSTIC LOGGING ==================
VERBOSE = os.getenv("VERBOSE", "0").strip().lower() in ("1", "true", "yes", "y")
VERBOSE_TECH = os.getenv("VERBOSE_TECH", "0").strip().lower() in ("1", "true", "yes", "y")
VERBOSE_MAX = int(os.getenv("VERBOSE_MAX", "50") or 50)
TECH_GATE = os.getenv("TECH_GATE", "0").strip().lower() in ("1", "true", "yes", "y")
_reject_logged = 0
_feature_cache = {}
def vlog(msg: str) -> None:
    if VERBOSE:
        print(msg)
def _get_sample_cached(ticker: str):
    # build_features() yfinance chaqirishi mumkin — faqat VERBOSE_TECH bo'lsa ishlatamiz
    if ticker in _feature_cache:
        return _feature_cache[ticker]
    try:
        s = build_features(ticker)
    except Exception:
        s = None
    _feature_cache[ticker] = s
    return s
def _vol_score(atr_ratio, lo: float = 0.0015, hi: float = 0.0060) -> float:
    # M5 uchun (taxminiy) ATR/Close diapazoniga mos normalize
    try:
        if atr_ratio is None:
            return 0.5
        x = (float(atr_ratio) - lo) / (hi - lo + 1e-12)
        return max(0.0, min(1.0, x))
    except Exception:
        return 0.5
def dynamic_rsi_bounds(atr_ratio):
    s = _vol_score(atr_ratio)
    # past vol -> 35/65, yuqori vol -> 25/75
    return (35.0 - 10.0 * s, 65.0 + 10.0 * s)
def explain_reject(p) -> str:
    # p: Pick (ticker, signal, p, threshold, side)
    ticker = getattr(p, "ticker", "?")
    sig = str(getattr(p, "signal", "HOLD"))
    prob = float(getattr(p, "p", 0.0) or 0.0)
    th = getattr(p, "threshold", None)
    side = getattr(p, "side", "NONE")
    u = sig.upper()
    if "CONFLICT" in u:
        reason = "conflict_signal"
    elif "HOLD" in u:
        if th is not None and prob < float(th):
            reason = "p_below_threshold"
        else:
            reason = "hold"
    else:
        reason = "unknown"
    msg = f"[REJECT] {ticker} reason={reason} sig={sig} p={prob:.2f}" + (f" th={float(th):.2f}" if th is not None else "") + f" side={side}"
    if VERBOSE_TECH:
        s = _get_sample_cached(ticker)
        if not s:
            msg += " | tech=NONE (features/data missing)"
        else:
            rsi_v = s.get("rsi")
            atr_ratio = s.get("atr_ratio")
            close_vs_ema = s.get("close_vs_ema")
            breakout = s.get("breakout")
            vol_z = s.get("vol_z")
            is_cons = s.get("is_consolidation")
            rlo, rhi = dynamic_rsi_bounds(atr_ratio)
            msg += (
                " | tech="
                f"rsi={rsi_v} (dyn {rlo:.1f}-{rhi:.1f}), "
                f"atr_ratio={atr_ratio}, close_vs_ema={close_vs_ema}, "
                f"breakout={breakout}, is_consolidation={is_cons}, vol_z={vol_z}"
            )
    return msg
def tech_gate_reason(sample: dict, side: str) -> list[str]:
    """Dynamic RSI/EMA/Consolidation gate (ATR ga qarab). Faqat TECH_GATE=1 bo'lsa ishlatiladi."""
    reasons = []
    if not sample:
        return ["no_features"]
    rsi_v = sample.get("rsi")
    atr_ratio = sample.get("atr_ratio")
    cve = sample.get("close_vs_ema")
    is_cons = sample.get("is_consolidation")
    breakout = sample.get("breakout")
    vol_z = sample.get("vol_z")
    # Dynamic RSI trigger (BUY uchun pullback, SELL uchun rally)
    s = _vol_score(atr_ratio)
    buy_trigger = 50.0 - 10.0 * s
    sell_trigger = 50.0 + 10.0 * s
    try:
        if rsi_v is not None:
            r = float(rsi_v)
            if side == "BUY" and r > buy_trigger:
                reasons.append(f"rsi_not_pullback(rsi={r:.1f}> {buy_trigger:.1f})")
            if side == "SELL" and r < sell_trigger:
                reasons.append(f"rsi_not_rally(rsi={r:.1f}< {sell_trigger:.1f})")
    except Exception:
        pass
    # EMA trend gate (minimal)
    try:
        if cve is not None:
            cve_i = int(cve)
            if side == "BUY" and cve_i != 1:
                reasons.append("below_ema")
            if side == "SELL" and cve_i != 0:
                reasons.append("above_ema")
    except Exception:
        pass
    # Consolidation: breakout yoki vol spike bo'lmasa ehtiyot
    try:
        if is_cons:
            if not breakout and (vol_z is None or float(vol_z) < 1.2):
                reasons.append("consolidation_no_breakout")
    except Exception:
        pass
    return reasons
# ================================================================
'''.strip("\n")
    s = insert_block(
        s,
        verbose_block,
        markers=[
            "PENDING_TTL_SEC",
            "WATCHLIST_FILE",
            "STATE_FILE",
            "def pick_best",
        ],
    )
    # Patch HOLD/CONFLICT continue block to print reasons
    # Try to detect variable name used in loop: u = <var>.signal.upper()
    pat = re.compile(
        r"(u\s*=\s*(?P<var>\w+)\.signal\.upper\(\)\s*\n\s*if\s+\"HOLD\"\s+in\s+u\s+or\s+\"CONFLICT\"\s+in\s+u\s*:\s*\n\s*)continue",
        flags=re.M,
    )
    m = pat.search(s)
    if m:
        var = m.group("var")
        repl = (
            m.group(1)
            + f"global _reject_logged\n"
              f"    if VERBOSE and _reject_logged < VERBOSE_MAX:\n"
              f"        vlog(explain_reject({var}))\n"
              f"        _reject_logged += 1\n"
              f"    # optional: TECH gate faqat debug uchun\n"
              f"    if TECH_GATE and VERBOSE_TECH:\n"
              f"        smp = _get_sample_cached({var}.ticker)\n"
              f"        if smp:\n"
              f"            rs = tech_gate_reason(smp, {var}.side)\n"
              f"            if rs:\n"
              f"                vlog(f\"[TECH_FAIL] {{{var}.ticker}} side={{{var}.side}} -> \" + \",\".join(rs))\n"
              f"    continue"
        )
        s = pat.sub(repl, s, count=1)
        print("[patch] watch_best: HOLD/CONFLICT reject logging added")
    else:
        print("[warn] watch_best: HOLD/CONFLICT pattern topilmadi — reject logging qo‘shilmadi (manual kerak bo‘lishi mumkin).")
    WB.write_text(s, encoding="utf-8")
    print("[ok] patched:", WB)
# ---------- Patch multi_predict.py ----------
def patch_multi_predict():
    if not MP.exists():
        raise SystemExit(f"multi_predict.py topilmadi: {MP}")
    backup(MP)
    s = MP.read_text(encoding="utf-8")
    # Ensure requests + retry imports exist
    needed_lines = [
        "import requests",
        "from requests.adapters import HTTPAdapter",
        "from urllib3.util.retry import Retry",
    ]
    for ln in needed_lines:
        if ln not in s:
            s = ensure_import(s, ln)
    session_block = r'''
# ================== YFINANCE SESSION / RETRY / TIMEOUT ==================
def make_yf_session() -> "requests.Session":
    s = requests.Session()
    # Minimal headerlar (barqarorlik uchun). Agressiv "browser spoof" shart emas.
    s.headers.update({
        "User-Agent": "trade_ai/1.0 (+local)",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json,text/plain,*/*",
    })
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s
_YF_SESSION = make_yf_session()
def download_yf(*args, **kwargs):
    # Defaultlar (siz yozgan kwargs ustun)
    kwargs.setdefault("progress", False)
    kwargs.setdefault("threads", False)
    kwargs.setdefault("timeout", 5)     # osilib qolmasin
    kwargs.setdefault("session", _YF_SESSION)
    return yf.download(*args, **kwargs)
# =======================================================================
'''.strip("\n")
    s = insert_block(
        s,
        session_block,
        markers=[
            "import yfinance",
            "import yfinance as yf",
            "yf =",
            "def build_features",
        ],
    )
    # Replace yf.download( ... ) -> download_yf( ... )
    if "yf.download(" in s and "download_yf(" not in s:
        s = s.replace("yf.download(", "download_yf(")
        print("[patch] multi_predict: yf.download -> download_yf wrapper applied")
    else:
        print("[info] multi_predict: yf.download replace skipped (maybe already patched)")
    MP.write_text(s, encoding="utf-8")
    print("[ok] patched:", MP)
if __name__ == "__main__":
    patch_watch_best()
    patch_multi_predict()
    print("\nDONE ✅  Endi .env ga VERBOSE=1 qo‘yib botni ishga tushiring.")
