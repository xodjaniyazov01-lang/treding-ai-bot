import csv

INP = "patterns_bulk.csv"
OUT = "patterns_bulk.cleaned.csv"
EXPECTED = 14

HEADER = [
    "pattern_name","side","st_3m","st_1h","st_4h","trend_align",
    "is_consolidation","breakout","volume_spike","neckline_break",
    "atr_ratio","rsi","close_vs_ema","label"
]

def main():
    rows = []
    bad = []

    with open(INP, "r", encoding="utf-8") as f:
        raw_lines = [line.strip() for line in f if line.strip() != ""]

    # Header 2 qatorga bo‘lingan bo‘lsa, birlashtiramiz
    first = raw_lines[0]
    if first.endswith(",") and len(raw_lines) > 1:
        first = first + raw_lines[1]
        raw_lines = [first] + raw_lines[2:]

    # CSV parse
    for i, line in enumerate(raw_lines, start=1):
        row = next(csv.reader([line]))
        if i == 1:
            rows.append(HEADER)  # header’ni standart qilib yozamiz
            continue

        if len(row) == EXPECTED:
            rows.append(row)
        else:
            bad.append((i, len(row), line))

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)

    print(f"✅ Clean file: {OUT}")
    print(f"✅ OK rows: {len(rows)-1}")
    print(f"⚠️ Bad rows: {len(bad)}")
    if bad:
        print("\nTop 10 bad rows:")
        for x in bad[:10]:
            print(f"Line {x[0]} fields={x[1]} -> {x[2]}")

if __name__ == "__main__":
    main()
