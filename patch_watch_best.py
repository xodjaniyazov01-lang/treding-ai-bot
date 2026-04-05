from pathlib import Path

p = Path("src/trade_ai/app/watch_best.py")
s = p.read_text(encoding="utf-8")

# watchlist o‘qishni utf-8-sig ga o‘zgartirish (BOM fix)
s = s.replace("WATCHLIST.read_text(encoding=\"utf-8\", errors=\"ignore\")",
              "WATCHLIST.read_text(encoding=\"utf-8-sig\", errors=\"ignore\")")

# agar yuqoridagi topilmasa, oddiy read_text bo‘lsa ham patch
s = s.replace("WATCHLIST.read_text(encoding=\"utf-8\", errors=\"ignore\")",
              "WATCHLIST.read_text(encoding=\"utf-8-sig\", errors=\"ignore\")")

# har doim ticker tozalash (BOM + bo‘sh joy)
if "def _clean_ticker" not in s:
    helper = """
def _clean_ticker(x: str) -> str:
    return (x or "").replace("\\ufeff","").strip().upper()
"""
    # helper-ni ROOT/LEGACY dan keyin qo‘shamiz
    marker = "LEGACY ="
    idx = s.find(marker)
    if idx != -1:
        # marker qatoridan keyin qo‘shish
        line_end = s.find("\n", idx)
        s = s[:line_end+1] + helper + s[line_end+1:]
    else:
        s = helper + "\n" + s

# load_watchlist ichida tickerni _clean_ticker bilan o‘qitish
s = s.replace("out.append(t.upper())", "out.append(_clean_ticker(t))")
s = s.replace("return [\"SPY\",\"AAPL\",\"MSFT\",\"NVDA\",\"TSLA\",\"META\",\"AMZN\",\"GOOGL\",\"XLK\"]",
              "return [\"SPY\",\"AAPL\",\"MSFT\",\"NVDA\",\"TSLA\",\"META\",\"AMZN\",\"GOOGL\",\"XLK\"]")

p.write_text(s, encoding="utf-8")
print("✅ Patched watch_best.py for BOM tickers.")
