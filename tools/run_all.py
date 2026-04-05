from __future__ import annotations

import os
import sys
import time
import subprocess
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _build_env() -> dict:
    env = os.environ.copy()

    # trade_ai paketini topishi uchun
    src_str = str(SRC)
    pp = env.get("PYTHONPATH", "")
    parts = [p for p in pp.split(os.pathsep) if p]
    if src_str not in parts:
        parts.insert(0, src_str)
    env["PYTHONPATH"] = os.pathsep.join(parts)

    # konsol uchun UTF-8
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _pump(prefix: str, pipe):
    try:
        for line in iter(pipe.readline, ""):
            if not line:
                break
            sys.stdout.write(prefix + line)
            sys.stdout.flush()
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def main():
    # Windows'da emoji "??" bo‘lib qolmasligi uchun (ixtiyoriy)
    if os.name == "nt":
        try:
            subprocess.run("chcp 65001 >nul", shell=True, cwd=str(ROOT))
        except Exception:
            pass

    env = _build_env()

    procs: list[tuple[str, subprocess.Popen]] = []

    cmds = [
        ("[FB] ", [sys.executable, "-m", "trade_ai.legacy.telegram_feedback_bot"]),
        ("[WB] ", [sys.executable, "-m", "trade_ai.app.watch_best"]),
    ]

    for prefix, cmd in cmds:
        p = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        procs.append((prefix, p))
        t = threading.Thread(target=_pump, args=(prefix, p.stdout), daemon=True)
        t.start()

    print("\n✅ Ikkala bot ishga tushdi. To'xtatish: CTRL+C\n")

    try:
        while True:
            for _, p in procs:
                rc = p.poll()
                if rc is not None:
                    raise RuntimeError(f"Process chiqib ketdi: {p.args} rc={rc}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 To'xtatyapman...")
    except Exception as e:
        print(f"\n⚠️ {e}")
    finally:
        for _, p in procs:
            if p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass

        t0 = time.time()
        while time.time() - t0 < 5:
            if all(p.poll() is not None for _, p in procs):
                break
            time.sleep(0.2)

        for _, p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass

        print("✅ Hammasi to'xtadi.")


if __name__ == "__main__":
    main()
