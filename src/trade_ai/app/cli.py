from __future__ import annotations
import argparse
from .watcher import main as watch_main
from .trainer import main as train_main

def main():
    p = argparse.ArgumentParser(prog="trade_ai")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("watch")
    sub.add_parser("train")

    args, rest = p.parse_known_args()

    if args.cmd == "watch":
        # pass rest args to legacy watcher
        import sys
        sys.argv = ["watch"] + rest
        watch_main()
    elif args.cmd == "train":
        train_main()

if __name__ == "__main__":
    main()
