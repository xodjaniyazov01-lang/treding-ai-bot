import pandas as pd
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "patterns.csv")
BULK = os.path.join(HERE, "patterns_bulk.cleaned.csv")

def main():
    if not os.path.exists(BULK):
        print("❌ patterns_bulk.cleaned.csv topilmadi")
        return

    df_main = pd.read_csv(MAIN) if os.path.exists(MAIN) else pd.DataFrame()
    df_bulk = pd.read_csv(BULK)

    # Bir xil ustunlar tartibi
    cols = list(df_bulk.columns)
    if df_main.empty:
        df_main = pd.DataFrame(columns=cols)
    else:
        df_main = df_main[cols]

    before = len(df_main)

    # ✅ Bulk ichida o'zining duplicate’larini olib tashlaymiz
    df_bulk = df_bulk.drop_duplicates()

    # ✅ “faqat yangi satrlarni” topish:
    # satrni tuple qilib, set bilan solishtiramiz
    main_set = set(map(tuple, df_main.astype(str).values.tolist()))
    bulk_rows = df_bulk.astype(str).values.tolist()

    new_rows = [r for r in bulk_rows if tuple(r) not in main_set]

    if new_rows:
        df_new = pd.DataFrame(new_rows, columns=cols)
        df_all = pd.concat([df_main, df_new], ignore_index=True)
    else:
        df_all = df_main

    after = len(df_all)
    added = after - before

    df_all.to_csv(MAIN, index=False)

    print(f"✅ Qo‘shildi: {added} ta pattern (faqat yangi satrlar)")
    print(f"📊 Jami patternlar: {after}")

if __name__ == "__main__":
    main()
