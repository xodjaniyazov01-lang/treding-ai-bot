from pathlib import Path
import re
root = Path(".").resolve()
mp = root / "src" / "trade_ai" / "legacy" / "multi_predict.py"
wb = root / "src" / "trade_ai" / "app" / "watch_best.py"
# --- patch multi_predict import ---
s = mp.read_text(encoding="utf-8", errors="ignore")
s2 = s.replace("from ..legacy.fundamentals_cache import get_fundamentals",
               "from trade_ai.legacy.fundamentals_cache import get_fundamentals")
if s2 != s:
    mp.write_text(s2, encoding="utf-8")
    print("✅ Patched multi_predict import -> absolute")
else:
    print("ℹ️ multi_predict import already ok (or different line)")
# --- patch watch_best subprocess to use -m module ---
t = wb.read_text(encoding="utf-8", errors="ignore")
# 1) cmd = [sys.executable, str(mp), "--auto"]  ->  cmd = [sys.executable, "-m", "trade_ai.legacy.multi_predict", "--auto"]
t2 = re.sub(
    r'cmd\s*=\s*\[\s*sys\.executable\s*,\s*str\(mp\)\s*,\s*"--auto"\s*\]',
    'cmd = [sys.executable, "-m", "trade_ai.legacy.multi_predict", "--auto"]',
    t
)
# 2) agar mp.exists() check bo‘lsa qolsin (zarar qilmaydi)
if t2 != t:
    wb.write_text(t2, encoding="utf-8")
    print("✅ Patched watch_best: run multi_predict via -m trade_ai.legacy.multi_predict")
else:
    print("ℹ️ watch_best already uses -m (or pattern different)")
print("DONE")
