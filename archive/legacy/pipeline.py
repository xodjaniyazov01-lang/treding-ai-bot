import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

def run(cmd):
    print("\n▶", " ".join(cmd))
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode != 0:
        raise SystemExit(r.returncode)

def truncate_file(path):
    # bulk faylni bo‘shatib qo‘yadi (faqat header qoldiramiz)
    header = "pattern_name,side,st_3m,st_1h,st_4h,trend_align,is_consolidation,breakout,volume_spike,neckline_break,atr_ratio,rsi,close_vs_ema,label\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)

def main():
    bulk = os.path.join(HERE, "patterns_bulk.csv")
    cleaned = os.path.join(HERE, "patterns_bulk.cleaned.csv")

    if os.path.exists(bulk):
        run([PY, "clean_bulk.py"])
        run([PY, "import_bulk.py"])

        # ✅ import bo‘lgach bulkni tozalab qo‘yamiz
        truncate_file(bulk)
        if os.path.exists(cleaned):
            os.remove(cleaned)

        print("🧹 patterns_bulk.csv tozalandi (header qoldi).")
    else:
        print("ℹ️ patterns_bulk.csv topilmadi, bulk import o'tkazib yuborildi.")

    run([PY, "train.py"])
    # run([PY, "predict.py"])
    run([PY, "predict.py", "--auto"])
    run([PY, "stats.py"])

    print("\n✅ PIPELINE DONE")

if __name__ == "__main__":
    main()
