import pandas as pd

INP = "patterns.csv"
OUT = "patterns.fixed.csv"

EXPECTED_COLS = [
    "pattern_name","side","st_3m","st_1h","st_4h","trend_align",
    "is_consolidation","breakout","volume_spike","neckline_break",
    "atr_ratio","rsi","close_vs_ema","label"
]

def main():
    # engine python: ba'zi buzilgan CSV'larda yaxshi ishlaydi
    df = pd.read_csv(INP, engine="python")

    # Agar ustunlar noto‘g‘ri bo‘lsa, qayta nomlashga harakat
    if list(df.columns) != EXPECTED_COLS:
        # Agar label ustuni bo'lmasa yoki ustunlar aralash bo'lsa:
        # faqat EXPECTED_COLS mavjud bo'lganlarini olamiz
        cols = [c for c in EXPECTED_COLS if c in df.columns]
        df = df[cols].copy()

    # labelni tozalash: faqat 0/1 qoldiramiz
    df["label"] = pd.to_numeric(df["label"], errors="coerce")
    df = df[df["label"].isin([0, 1])].copy()
    df["label"] = df["label"].astype(int)

    # numeric ustunlar tozalash
    numeric_cols = [c for c in EXPECTED_COLS if c not in ["pattern_name", "side"]]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # asosiy featurelar bo'sh bo'lsa tashlaymiz
    must_have = ["st_3m","st_1h","st_4h","breakout","volume_spike","label"]
    for c in must_have:
        if c in df.columns:
            df = df.dropna(subset=[c])

    # ustunlarni to'liq tartibga keltiramiz (borlarini)
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = None
    df = df[EXPECTED_COLS]

    df.to_csv(OUT, index=False)
    print("✅ Fixed file:", OUT)
    print("✅ Rows:", len(df))
    print("✅ Label counts:", df["label"].value_counts().to_dict())

if __name__ == "__main__":
    main()
