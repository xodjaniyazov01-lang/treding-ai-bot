# Task 07 Handoff

Date: 2026-05-05

## Maqsad

Signal yuborilgandan 1 soat o'tib, narx foydaga ketdimi yoki zararga ketdimi, shuni avtomatik tekshirish qo'shildi.

Bu TP/SL close logikadan alohida ishlaydi. Maqsad: signal quality ni 1 soatlik self-validation orqali Telegram va DB ga yozib borish.

## Qaysi fayllar o'zgardi

- `src/trade_ai/services/db.py`
- `src/trade_ai/services/validator.py`
- `src/trade_ai/services/telegram.py`
- `src/trade_ai/app/watch_best.py`

## Yangi DB ustunlar

`signals` jadvaliga quyidagi ustunlar qo'shildi:

- `price_at_signal REAL`
- `price_at_check REAL`
- `pnl_pct REAL`
- `validated_at TEXT`
- `validation_outcome TEXT`

## Ma'no

- `price_at_signal`: signal yuborilgan paytdagi narx
- `price_at_check`: validator tekshirgan paytdagi narx
- `pnl_pct`: 1 soat ichidagi profit/loss foizi
- `validated_at`: validator ishlagan vaqt
- `validation_outcome`: `PENDING`, `WIN`, `LOSS`

## Ishlash tartibi

### 1. Signal yaratilganda

`watch_best.py` ichida signal DB ga yozilganda:

- `price_at_signal=entry`
- `validation_outcome='PENDING'`

saqlanadi.

### 2. Har cycle boshida

`watch_best.py` ichida:

- eski `OPEN` signallar uchun eski TP/SL close-check ishlaydi
- keyin `validate_pending()` chaqiriladi

### 3. Validator qaysi signallarni oladi

`validator.py` faqat quyidagilarni tekshiradi:

- `status='OPEN'`
- `validated_at IS NULL`
- `validation_outcome='PENDING'`
- signal vaqtidan kamida 1 soat o'tgan

### 4. WIN / LOSS qoidasi

- `BUY` uchun: narx oshsa `WIN`, tushsa `LOSS`
- `SELL` uchun: narx tushsa `WIN`, oshsa `LOSS`

Hisob:

- `BUY`: `(price_now - price_open) / price_open * 100`
- `SELL`: `(price_open - price_now) / price_open * 100`

### 5. Telegram xabar

Validator natijasi alohida Telegram message bo'lib ketadi:

- `✅ WIN: TICKER BUY`
- yoki `❌ LOSS: TICKER SELL`

Message format `build_validation_message()` ichida.

## Muhim eslatma

Loyihada oldindan bor bo'lgan `outcome` maydoni TP/SL close logika uchun ishlatilgan.

Task 07 da 1 soatlik natija uchun asosiy ishonchli maydon:

- `validation_outcome`

`outcome` ham validator ichida `WIN` yoki `LOSS` qilib yoziladi, lekin keyinchalik eski TP/SL close-flow uni `TP`, `SL`, yoki `AMBIGUOUS` ga overwrite qilishi mumkin.

Shuning uchun keyingi dasturchi 1 soatlik self-validation statistikasi uchun `validation_outcome` ustuniga qarasin.

## Migratsiya

`db.init_db()` ichida `ensure_signal_schema()` qo'shilgan.

U:

- yetishmayotgan ustunlarni `ALTER TABLE` bilan qo'shadi
- eski rowlarda `price_at_signal = entry` qilib to'ldiradi
- `OPEN` va hali tekshirilmagan rowlar uchun `validation_outcome='PENDING'` qo'yadi

Demak eski `OPEN` signallar ham validatorga tushishi mumkin.

## Nega eski signal darrov tekshirilmay qolishi mumkin

Quyidagi holatda validator hech narsa qilmaydi:

- 1 soat hali to'lmagan bo'lsa
- signal `CLOSED` bo'lsa
- `entry` / `price_at_signal` bo'sh bo'lsa
- latest price olib bo'lmasa

## Qanday tekshiriladi

### Hali tekshirilmaganlar

```sql
SELECT id, ticker, side, ts, validation_outcome
FROM signals
WHERE status='OPEN' AND validation_outcome='PENDING';
```

### Tekshirilganlar

```sql
SELECT id, ticker, side, validation_outcome, pnl_pct, price_at_signal, price_at_check, validated_at
FROM signals
WHERE validation_outcome IN ('WIN', 'LOSS')
ORDER BY ts DESC;
```

## Runtime

Kod tushishi uchun running bot restart bo'lishi kerak.

Start:

```powershell
$env:PYTHONPATH = "src"
python -m trade_ai.app.watch_best
```

## Keyingi dasturchi uchun tavsiya

1. `validation_outcome` bo'yicha alohida stats qo'shish
2. Validator eventlarini logda aniqroq yozish
3. `outcome` va `validation_outcome` ni semantik jihatdan ajratib, chalkashlikni kamaytirish
4. SQLite o'rniga persistent DB ishlatish, agar Railway yoki remote deploy davom etsa
