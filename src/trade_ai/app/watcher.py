from __future__ import annotations
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEGACY = ROOT / "src" / "trade_ai" / "legacy"

def run_legacy(script_name: str, args: list[str]) -> int:
    script = LEGACY / script_name
    if not script.exists():
        print(f"❌ Legacy script not found: {script}")
        return 1
    cmd = [sys.executable, str(script)] + args
    return subprocess.call(cmd)

def main():
    # default: realtime watch pro
    raise SystemExit(run_legacy("realtime_watch_pro.py", sys.argv[1:]))

if __name__ == "__main__":
    main()
