from pathlib import Path
p = Path(r"src\trade_ai\legacy\multi_predict.py")
s = p.read_text(encoding="utf-8")
cnt_before = s.count(r'\"\"\"')
s = s.replace(r'\"\"\"', '"""')
cnt_after = s.count(r'\"\"\"')
p.write_text(s, encoding="utf-8")
print("OK: replaced", cnt_before, "->", cnt_after)
