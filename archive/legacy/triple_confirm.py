from __future__ import annotations

import argparse

import joblib
import pandas as pd

from ..legacy import multi_predict


def get_signals(tickers: list[str]) -> dict[str, tuple[str, float]]:
    """{ticker: (signal, p_win)}"""
    if not multi_predict.MODEL_PATH.exists():
        return {}

    model = joblib.load(multi_predict.MODEL_PATH)
    th = multi_predict.load_threshold()

    out: dict[str, tuple[str, float]] = {}

    for t in tickers:
        sample = multi_predict.build_features(t)
        if sample is None:
            out[t] = ("HOLD", 0.50)
            continue

        p_win = float(model.predict_proba(pd.DataFrame([sample]))[0][1])
        sig = multi_predict.to_signal(p_win, sample.get("side", "BUY"), th)
        out[t] = (sig, p_win)

    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--need", type=int, default=2)
    args = parser.parse_args()

    tickers = multi_predict.load_watchlist()
    signals = get_signals(tickers)

    if not signals:
        print("❌ Signal topilmadi (model yoki data muammo)")
        return

    buy_count = 0
    sell_count = 0

    spy_sig, spy_p = signals.get("SPY", ("HOLD", 0.0))

    for sig, _p in signals.values():
        if sig in ("BUY", "STRONG_BUY"):
            buy_count += 1
        elif sig in ("SELL", "STRONG_SELL"):
            sell_count += 1

    # MARKET
    market = "HOLD"
    if spy_sig in ("BUY", "STRONG_BUY"):
        market = "BUY"
    elif spy_sig in ("SELL", "STRONG_SELL"):
        market = "SELL"

    print(f"✅ MARKET: {spy_sig}({spy_p:.2f}) => {market}")

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

    print(
        f"✅ FINAL: {final} (need={args.need}, buy={buy_count}, sell={sell_count}, total={len(signals)})"
    )


if __name__ == "__main__":
    main()
