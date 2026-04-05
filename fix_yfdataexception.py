from pathlib import Path
from datetime import datetime
import re
import py_compile
p = Path("src/trade_ai/legacy/multi_predict.py")
s = p.read_text(encoding="utf-8")
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
bak = p.with_suffix(p.suffix + f".bak_yf_fix_{ts}")
bak.write_text(s, encoding="utf-8")
print(f"[backup] {p} -> {bak}")
# 1) yf_download_safe funksiyasini to'liq almashtiramiz (session yo'q)
pat = re.compile(r"(?ms)^def\s+yf_download_safe\(.*?\n# =======================================================================\n")
new_block = """def yf_download_safe(ticker: str, *, period: str, interval: str, min_rows: int = 300):
    \\\"\\\"\\\"Return (df, err). Session uzatilmaydi (yfinance ba'zi versiyalarda session uchun YFDataException beradi).
    err: empty / short(n) / missing_cols / exception:TYPE:MSG
    \\\"\\\"\\\"
    import time
    last_err = None
    for attempt in range(3):
        try:
            df = yf.download(
                ticker,
                period=period,
                interval=interval,
                auto_adjust=False,
                group_by="column",
                progress=False,
                threads=False,
                timeout=5,
            )
        except Exception as e:
            msg = str(e).replace("\\n", " ")[:140]
            last_err = f"exception:{type(e).__name__}:{msg}"
            df = None
        if df is None or getattr(df, "empty", False):
            if last_err is None:
                last_err = "empty"
            time.sleep(1.0 * (2 ** attempt))
            continue
        # Flatten MultiIndex if any
        try:
            import pandas as pd
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            elif hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = [c[0] for c in df.columns]
        except Exception:
            pass
        if len(df) < min_rows:
            last_err = f"short({len(df)})"
            time.sleep(1.0 * (2 ** attempt))
            continue
        need = {"Open", "High", "Low", "Close", "Volume"}
        if not need.issubset(df.columns):
            last_err = "missing_cols"
            time.sleep(1.0 * (2 ** attempt))
            continue
        df = df.dropna().copy()
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        return df, None
    return None, (last_err or "unknown")
# =======================================================================
"""
m = pat.search(s)
if not m:
    raise SystemExit("[ERROR] yf_download_safe blokini topolmadim (pattern mos emas).")
s = pat.sub(new_block, s, count=1)
# 2) yf.download(...) ichida session=_YF_SESSION bo'lsa ham olib tashlaymiz (agar qolgan bo'lsa)
s = re.sub(r"(?m)^\s*session\s*=\s*_YF_SESSION\s*,\s*\n", "", s)
p.write_text(s, encoding="utf-8")
print("[ok] multi_predict.py yfinance session removed + retry/backoff added ✅")
py_compile.compile(str(p), doraise=True)
print("[ok] syntax check passed ✅")
