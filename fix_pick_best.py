from pathlib import Path
from datetime import datetime
import re
import py_compile
p = Path("src/trade_ai/app/watch_best.py")
txt = p.read_text(encoding="utf-8")
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
bak = p.with_suffix(p.suffix + f".bak_pickbest_{stamp}")
bak.write_text(txt, encoding="utf-8")
print(f"[backup] {p} -> {bak}")
pattern = re.compile(r"(?ms)^def\s+pick_best\s*\(.*?\n(?=^def\s+fetch_atr_entry\s*\()", re.M)
replacement = """def pick_best(picks: List[Pick]) -> Optional[Pick]:
    global _reject_logged
    cands: List[Pick] = []
    for x in picks:
        u = x.signal.upper()
        # HOLD/CONFLICT -> rad etish sababi (verbose)
        if "HOLD" in u or "CONFLICT" in u:
            if VERBOSE and _reject_logged < VERBOSE_MAX:
                vlog(explain_reject(x))
                _reject_logged += 1
            # Optional: TECH gate faqat debug uchun (signalni o'zgartirmaydi, faqat log)
            if TECH_GATE and VERBOSE_TECH:
                smp = _get_sample_cached(x.ticker)
                if smp:
                    rs = tech_gate_reason(smp, x.side)
                    if rs:
                        vlog(f"[TECH_FAIL] {x.ticker} side={x.side} -> " + ",".join(rs))
            continue
        # BUY/SELL kandidat
        if ("BUY" in u) or ("SELL" in u):
            cands.append(x)
    if not cands:
        return None
    cands.sort(key=lambda z: strength_score(z.signal, z.p), reverse=True)
    return cands[0]
"""
m = pattern.search(txt)
if not m:
    raise SystemExit("[ERROR] pick_best bloki topilmadi (pattern mos kelmadi).")
txt2 = pattern.sub(replacement, txt, count=1)
p.write_text(txt2, encoding="utf-8")
print("[ok] pick_best fixed ✅")
# syntax check
py_compile.compile(str(p), doraise=True)
print("[ok] syntax check passed ✅")
