import argparse
import subprocess
import re

def run_multi():
    r = subprocess.run(
        ["python", "multi_predict.py", "--auto"],
        capture_output=True,
        text=True
    )
    return r.stdout

def parse_signals(text):
    pattern = r"([A-Z]+):\s+([A-Z_]+)\s+\(p=([0-9.]+)"
    matches = re.findall(pattern, text)

    results = {}
    for ticker, signal, prob in matches:
        results[ticker] = (signal, float(prob))

    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--need", type=int, default=2)
    args = parser.parse_args()

    out = run_multi()
    signals = parse_signals(out)

    buy_count = 0
    sell_count = 0

    spy_sig = signals.get("SPY", ("HOLD", 0.0))[0]
    spy_p = signals.get("SPY", ("HOLD", 0.0))[1]

    for sig, p in signals.values():
        if sig in ["BUY", "STRONG_BUY"]:
            buy_count += 1
        elif sig in ["SELL", "STRONG_SELL"]:
            sell_count += 1

    # MARKET
    market = "HOLD"
    if spy_sig in ["BUY", "STRONG_BUY"]:
        market = "BUY"
    elif spy_sig in ["SELL", "STRONG_SELL"]:
        market = "SELL"

    print(f"MARKET: {spy_sig}({spy_p:.2f}) => {market}")

    # FINAL
    final = "HOLD"

    if buy_count >= args.need and sell_count == 0:
        final = "BUY"
    elif sell_count >= args.need and buy_count == 0:
        final = "SELL"
    elif buy_count >= args.need and sell_count >= 1:
        final = "CONFLICT"
    elif market != "HOLD":
        final = f"{market} (Market)"

    print(f"FINAL: {final} (need={args.need}, buy={buy_count}, sell={sell_count}, total={len(signals)})")

if __name__ == "__main__":
    main()
