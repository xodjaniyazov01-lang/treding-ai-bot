from __future__ import annotations
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEGACY = ROOT / "src" / "trade_ai" / "legacy"

def main():
    script = LEGACY / "train.py"
    if not script.exists():
        print("❌ legacy train.py topilmadi")
        raise SystemExit(1)
    raise SystemExit(subprocess.call([sys.executable, str(script)]))

if __name__ == "__main__":
    main()
