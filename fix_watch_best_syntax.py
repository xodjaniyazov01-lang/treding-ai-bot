from pathlib import Path
import re
p = Path("src/trade_ai/app/watch_best.py")
s = p.read_text(encoding="utf-8")
pattern = r'text\s*=\s*f"BEST SIGNAL.*?tg_send\(text\)'
replacement = (
'text = (\n'
'    f"BEST SIGNAL\\n\\n"\n'
'    f"Ticker: {best.ticker}\\n"\n'
'    f"Signal: {best.signal} (p={best.p:.2f})\\n\\n"\n'
'    f"Entry: {entry:.2f}\\n"\n'
'    f"StopLoss: {sl:.2f}\\n"\n'
'    f"TakeProfit: {tp:.2f}\\n\\n"\n'
'    f"Time: {now}\\n"\n'
')\n'
'code, resp = tg_send(text)'
)
new_s, n = re.subn(pattern, replacement, s, flags=re.S)
if n == 0:
    raise SystemExit("❌ Pattern topilmadi. watch_best.py ichida tg_send(text) bo‘lgan joyni topib bo‘lmadi.")
p.write_text(new_s, encoding="utf-8")
print("✅ Fixed syntax around BEST SIGNAL + tg_send(text)")
