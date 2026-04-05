from pathlib import Path
from datetime import datetime
import re
MP = Path("src/trade_ai/legacy/multi_predict.py")
txt = MP.read_text(encoding="utf-8")
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
bak = MP.with_suffix(MP.suffix + f".bak_req_{stamp}")
bak.write_text(txt, encoding="utf-8")
print(f"[backup] {MP} -> {bak}")
# def make_yf_session dan oldin requests importlari bor-yo'qligini tekshiramiz
m = re.search(r"^def\s+make_yf_session\s*\(", txt, flags=re.M)
if not m:
    raise SystemExit("[ERROR] def make_yf_session topilmadi (multi_predict.py ichida).")
head = txt[:m.start()]
need = []
if "import requests" not in head:
    need.append("import requests")
if "from requests.adapters import HTTPAdapter" not in head:
    need.append("from requests.adapters import HTTPAdapter")
if "from urllib3.util.retry import Retry" not in head:
    need.append("from urllib3.util.retry import Retry")
if not need:
    print("[info] requests importlari allaqachon def make_yf_session dan oldin bor ✅")
else:
    insert = "\n".join(need) + "\n\n"
    txt = txt[:m.start()] + insert + txt[m.start():]
    MP.write_text(txt, encoding="utf-8")
    print("[ok] imports inserted ✅:", ", ".join(need))
# tez tekshiruv: modul import bo'ladimi?
import py_compile
py_compile.compile(str(MP), doraise=True)
print("[ok] syntax check passed ✅")
