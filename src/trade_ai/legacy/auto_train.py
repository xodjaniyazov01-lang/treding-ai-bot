import os
import time
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BULK = os.path.join(HERE, "patterns_bulk.csv")
PIPELINE = os.path.join(HERE, "pipeline.py")

CHECK_EVERY_SEC = 3  # har 3 soniyada tekshiradi

def run_pipeline():
    py = sys.executable  # .venv python
    print("\n▶ AUTO: pipeline start")
    subprocess.run([py, PIPELINE], check=False)
    print("✅ AUTO: pipeline done\n")

def main():
    print("🟢 AUTO TRAIN watcher ishga tushdi.")
    print("📌 patterns_bulk.csv o'zgarsa — pipeline avtomatik ishlaydi.")
    print("❗ To'xtatish: CTRL + C\n")

    last_mtime = None

    while True:
        try:
            if os.path.exists(BULK):
                mtime = os.path.getmtime(BULK)
                if last_mtime is None:
                    last_mtime = mtime
                elif mtime != last_mtime:
                    last_mtime = mtime
                    run_pipeline()
            time.sleep(CHECK_EVERY_SEC)
        except KeyboardInterrupt:
            print("\n🛑 AUTO TRAIN to'xtadi.")
            break

if __name__ == "__main__":
    main()
