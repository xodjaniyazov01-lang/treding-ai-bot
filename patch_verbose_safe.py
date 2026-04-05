from __future__ import annotations
from pathlib import Path
from datetime import datetime
import re
ROOT = Path.cwd()
WB = ROOT / "src" / "trade_ai" / "app" / "watch_best.py"
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
def backup(p: Path):
    b = p.with_suffix(p.suffix + f".bakfix_{stamp}")
    b.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[backup] {p} -> {b}")
def ensure_import_os(text: str) -> str:
    if re.search(r"^\s*import\s+os\s*$", text, flags=re.M):
        return text
    lines = text.splitlines()
    last_imp = -1
    for i, ln in enumerate(lines[:250]):
        if ln.startswith("import ") or ln.startswith("from "):
            last_imp = i
    if last_imp >= 0:
        lines.insert(last_imp + 1, "import os")
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return "import os\n" + text
def insert_verbose_block(text: str) -> str:
    if "VERBOSE / DIAGNOSTIC LOGGING" in text:
        return text
    block = r'''
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
        s = build_features(ticker)  # watch_best odatda multi_predict dan import qiladi
    except Exception:
        s = None
    _feature_cache[ticker] = s
    return s
def _vol_score(atr_ratio, lo: float = 0.0015, hi: float = 0.0060) -> float:
    try:
        if atr_ratio is None:
            return 0.5
        x = (float(atr_ratio) - lo) / (hi - lo + 1e-12)
        return max(0.0, min(1.0, x))
    except Exception:
        return 0.5
def dynamic_rsi_bounds(atr_ratio):
    s = _vol_score(atr_ratio)
    return (35.0 - 10.0 * s, 65.0 + 10.0 * s)
def explain_reject(p) -> str:
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
    reasons = []
    if not sample:
        return ["no_features"]
    rsi_v = sample.get("rsi")
    atr_ratio = sample.get("atr_ratio")
    cve = sample.get("close_vs_ema")
    is_cons = sample.get("is_consolidation")
    breakout = sample.get("breakout")
    vol_z = sample.get("vol_z")
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
    try:
        if cve is not None:
            cve_i = int(cve)
            if side == "BUY" and cve_i != 1:
                reasons.append("below_ema")
            if side == "SELL" and cve_i != 0:
                reasons.append("above_ema")
    except Exception:
        pass
    try:
        if is_cons:
            if not breakout and (vol_z is None or float(vol_z) < 1.2):
                reasons.append("consolidation_no_breakout")
    except Exception:
        pass
    return reasons
# ================================================================
'''.strip("\n")
    # insert before def pick_best (best marker)
    m = re.search(r"^def\s+pick_best\s*\(", text, flags=re.M)
    if m:
        i = m.start()
        return text[:i] + block + "\n\n" + text[i:]
    return block + "\n\n" + text
def add_global_in_pick_best(text: str) -> str:
    # Add 'global _reject_logged' right after def pick_best line (once)
    if re.search(r"^\s*global\s+_reject_logged\s*$", text, flags=re.M):
        return text
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r"^def\s+pick_best\s*\(", ln):
            # insert next line with 4-space indent
            lines.insert(i+1, "    global _reject_logged")
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return text
def patch_reject_block(text: str) -> str:
    # Find var name from "u = <var>.signal.upper()"
    var = "x"
    m = re.search(r"^\s*u\s*=\s*(\w+)\.signal\.upper\(\)\s*$", text, flags=re.M)
    if m:
        var = m.group(1)
    lines = text.splitlines()
    for i in range(len(lines)):
        if re.search(r'if\s+"HOLD"\s+in\s+u\s+or\s+"CONFLICT"\s+in\s+u\s*:', lines[i]):
            indent = re.match(r"^(\s*)", lines[i]).group(1)
            # find the next line that is just 'continue' (same indent+4 or more)
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            # we expect continue at j
            if j < len(lines) and lines[j].strip() == "continue":
                new_block = [
                    lines[i],  # keep the if line
                    indent + "    if VERBOSE and _reject_logged < VERBOSE_MAX:",
                    indent + f"        vlog(explain_reject({var}))",
                    indent + "        _reject_logged += 1",
                    indent + "    if TECH_GATE and VERBOSE_TECH:",
                    indent + f"        smp = _get_sample_cached({var}.ticker)",
                    indent + "        if smp:",
                    indent + f"            rs = tech_gate_reason(smp, {var}.side)",
                    indent + "            if rs:",
                    indent + f"                vlog(f\"[TECH_FAIL] {{{var}.ticker}} side={{{var}.side}} -> \" + \",\".join(rs))",
                    indent + "    continue",
                ]
                # replace i..j with new_block
                lines[i:j+1] = new_block
                return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
            else:
                # couldn't find continue; leave unchanged
                return text
    return text
def main():
    if not WB.exists():
        raise SystemExit(f"watch_best.py topilmadi: {WB}")
    backup(WB)
    txt = WB.read_text(encoding="utf-8")
    txt = ensure_import_os(txt)
    txt = insert_verbose_block(txt)
    txt = add_global_in_pick_best(txt)
    txt = patch_reject_block(txt)
    WB.write_text(txt, encoding="utf-8")
    print("[ok] watch_best patched safely ✅")
    # quick syntax check
    import py_compile
    py_compile.compile(str(WB), doraise=True)
    print("[ok] syntax check passed ✅")
if __name__ == "__main__":
    main()
