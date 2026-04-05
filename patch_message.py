from pathlib import Path
p = Path(r"src/trade_ai/app/watch_best.py")
s = p.read_text(encoding="utf-8")
# ===== ATR yo‘q bo‘lsa yuboriladigan xabar =====
s = s.replace(
    'code, _ = tg_send(f"🚨 {msg_core}\\nTime: {now}")',
    'code, _ = tg_send(f"BEST SIGNAL\\n\\nTicker: ${best.ticker}\\nSignal: {best.signal} (p={best.p:.2f})\\n\\nTime: {now}")'
)
# ===== Asosiy signal xabari (Entry/SL/TP bilan) =====
if "code, resp = tg_send(text)" in s:
    s = s.replace(
        "code, resp = tg_send(text)",
        'text = f"BEST SIGNAL\\n\\nTicker: ${best.ticker}\\nSignal: {best.signal} (p={best.p:.2f})\\n\\nEntry: {entry:.2f}\\nStopLoss: {sl:.2f}\\nTakeProfit: {tp:.2f}\\n\\nTime: {now}\\n"\\n                code, resp = tg_send(text)'
    )
p.write_text(s, encoding="utf-8")
print("✅ Message format patched successfully.")
