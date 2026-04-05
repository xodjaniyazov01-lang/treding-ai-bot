import pandas as pd

CSV = "patterns.csv"

def pct(x):
    return round(100 * x, 1)

def main():
    df = pd.read_csv(CSV)

    print("\n=== DATASET INFO ===")
    print("Rows:", len(df))
    print("WIN rate overall:", pct(df["label"].mean()), "%")

    print("\n=== BUY vs SELL ===")
    side_stats = df.groupby("side")["label"].agg(["count", "mean"]).reset_index()
    side_stats["win_rate_%"] = side_stats["mean"].apply(pct)
    print(side_stats[["side","count","win_rate_%"]].to_string(index=False))

    print("\n=== TOP PATTERNS (min 5 trades) ===")
    pat = df.groupby("pattern_name")["label"].agg(["count","mean"]).reset_index()
    pat = pat[pat["count"] >= 5].copy()
    pat["win_rate_%"] = pat["mean"].apply(pct)
    pat = pat.sort_values(["win_rate_%","count"], ascending=[False, False])
    print(pat[["pattern_name","count","win_rate_%"]].head(15).to_string(index=False))

    print("\n=== WORST PATTERNS (min 5 trades) ===")
    pat2 = pat.sort_values(["win_rate_%","count"], ascending=[True, False])
    print(pat2[["pattern_name","count","win_rate_%"]].head(15).to_string(index=False))

    print("\n=== FEATURE EFFECT (simple) ===")
    for col in ["breakout","volume_spike","is_consolidation","trend_align"]:
        if col in df.columns:
            g = df.groupby(col)["label"].agg(["count","mean"]).reset_index()
            g["win_rate_%"] = g["mean"].apply(pct)
            print(f"\n[{col}]")
            print(g[[col,"count","win_rate_%"]].to_string(index=False))

if __name__ == "__main__":
    main()
