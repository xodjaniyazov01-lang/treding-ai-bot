# trading-ai-bot

Telegram orqali stock/ETF trading signallarini yuboradigan Python bot. Bot watchlistdagi tickerlarni yfinance orqali skanerlaydi, `model.joblib` ML modeli bilan signal ehtimolini hisoblaydi, trend/volatility filtrlaridan o'tkazadi va eng yaxshi setupni Telegramga WIN/LOSS tugmalari bilan yuboradi.

## Nima Qiladi

- `data/watchlist.txt` ichidagi tickerlarni M5, M15, H1 yoki H4 timeframe bo'yicha kuzatadi.
- yfinance xatolari uchun retry/backoff, cache va global download lock ishlatadi.
- Bir vaqtda bir nechta predict/download chaqiruvida race condition bo'lmasligi uchun yfinance downloadlari lock ostida bajariladi.
- Signal sifati uchun threshold, ATR/RR, VIX, SPY trend, trend conflict va duplicate filtrlarini qo'llaydi.
- Telegram panelidan timeframe almashtirish, `/status`, `/backtest`, `/stats`, `/model`, `/health` buyruqlarini qo'llab-quvvatlaydi.
- Signalga bosilgan `To'g'ri` / `Noto'g'ri` Telegram feedbacklarini `feedback_log.csv`ga yozadi.
- Har kuni `DAILY_REPORT_TIME` vaqtida Telegramga signal monitoring hisobotini yuboradi.
- Ochiq signallarni tekshiradi, outcome statistikasi asosida `data/threshold.txt` qiymatini dinamik sozlaydi.

## O'rnatish

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` fayliga Telegram credentiallarini yozing:

```env
BOT_TOKEN=123456:ABCDEF...
CHAT_ID=123456789
PYTHONPATH=src
TEST_MODE=False
```

Production tickerlar `data/watchlist.txt` ichida saqlanadi.

## Ishga Tushirish

```powershell
$env:PYTHONPATH = "src"
python -m trade_ai.app.watch_best
```

Test rejim:

```powershell
$env:PYTHONPATH = "src"
$env:TEST_MODE = "True"
$env:TEST_TICKERS = "AAPL,TSLA,NVDA,MSFT,AMZN,META,SPY"
python -m trade_ai.app.watch_best
```

## Muhim Sozlamalar

- `DEFAULT_THRESHOLD`: `data/threshold.txt` bo'lmasa ishlatiladigan default threshold.
- `THRESHOLD_MIN` / `THRESHOLD_MAX`: training va auto-tune threshold chegaralari.
- `SLEEP_SEC`: skaner sikllari orasidagi kutish vaqti.
- `DUPLICATE_TTL_SEC` / `SIGNAL_COOLDOWN_SEC`: bir xil signalni qayta yubormaslik oynalari.
- `YF_RETRIES`, `YF_SINGLE_TIMEOUT_SEC`, `YF_BATCH_TIMEOUT_SEC`: yfinance barqarorligi.
- `TELEGRAM_TIMEOUT_SEC`, `TELEGRAM_POLL_TIMEOUT_SEC`: Telegram API timeoutlari.
- `DAILY_REPORT_TIME`: kunlik monitoring hisoboti vaqti, default `20:00` server vaqti.
- `AUTO_RETRAIN_FEEDBACK_STEP`: nechta yangi feedbackdan keyin model retrain qilinishi, default `50`.
- `ACCOUNT_EQUITY`, `RISK_PER_TRADE_PCT`, `MAX_DAILY_LOSS_PCT`: risk sozlamalari.
- `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`: runtime log rotation.

To'liq namuna: [.env.example](.env.example).

## Training

Modelni qayta o'rgatish:

```powershell
$env:PYTHONPATH = "src"
python -m trade_ai.app.trainer
```

Training loader quyidagi manbalarni birlashtiradi:

- `data/patterns.csv`
- `data/patterns_bulk.csv` agar mavjud bo'lsa
- `feedback_log.csv` agar unda model feature ustunlari va `label` mavjud bo'lsa
- `signals.csv` / `signals.log` agar mavjud bo'lsa backtest summary uchun o'qiladi

Kerakli ustunlar: `pattern_name, side, st_3m, st_1h, st_4h, trend_align, is_consolidation, breakout, volume_spike, neckline_break, atr_ratio, rsi, close_vs_ema, label`.

Bot feedback CSV formati:

```csv
timestamp,symbol,signal,confidence,timeframe,pattern_name,side,st_3m,st_1h,st_4h,trend_align,is_consolidation,breakout,volume_spike,neckline_break,atr_ratio,rsi,close_vs_ema,label
```

`label`: `1 = To'g'ri/WIN`, `0 = Noto'g'ri/LOSS`.

Training boshlanishidan oldin `feedback_log.csv` quality checkdan o'tadi. Feature ustunlari, `label` qiymati, `confidence` oralig'i va bo'sh qiymatlar tekshiriladi; muammoli rowlar logga warning yozilib skip qilinadi, training to'xtamaydi.

## Kunlik Hisobot

Bot har kuni `DAILY_REPORT_TIME`dan keyin bir marta Telegramga kunlik hisobot yuboradi. Hisobot `feedback_log.csv`dagi label bor rowlarga tayanadi, `signals.csv` mavjud bo'lsa signal sonlarini ham undan oladi.

Hisobot tarkibi:

- jami signal soni bugun / hafta
- WIN / LOSS va win rate
- eng yaxshi ticker
- eng yomon ticker
- o'rtacha confidence
- eng faol timeframe
- feedback progress: auto-retraining triggerigacha nechta yangi feedback bor/qoldi

Agar bugun feedback bo'lmasa, bot `Bugun feedback yo'q` deb xabar yuboradi va xatolik bermaydi.

## Status Komandasi

Telegramda `/status` komandasi botning umumiy holatini yuboradi:

- model yuklanganmi, model fayli bormi, threshold va F1
- training rows va oxirgi retrain vaqti
- feedback rows va auto-retraining progressi
- backtest win rate, avg PnL, best/worst ticker
- `signals_history.db`, `signals.csv`, `signals.log`, `backtest_results.json` mavjudligi

Telegramda `/backtest` komandasi `data/backtest_results.json`dan qisqa hisobot yuboradi. Fayl hali yo'q bo'lsa, bot `Backtest ma'lumoti hali yo'q` deb javob beradi va xatolik bermaydi.

## Backtest Export

`src/trade_ai/services/backtest.py` SQLite signal tarixini `signals.csv` va `signals.log` formatlariga eksport qiladi. Agar bu fayllar yo'q bo'lsa, backtest pipeline `data/signals_history.db`dan avtomatik generatsiya qiladi.

`signals.csv` formati:

```csv
signal_id,timestamp,symbol,signal,side,timeframe,interval,confidence,threshold,entry,sl,tp,status,outcome,close_timestamp,close_price,price_at_signal,price_at_check,pnl_pct,validation_outcome,validated_at,reason,model_version,pattern_name,st_3m,st_1h,st_4h,trend_align,is_consolidation,breakout,volume_spike,neckline_break,atr_ratio,rsi,close_vs_ema
```

`signals.log` JSONL formatida yoziladi: har qatorda bitta signal JSON object.

Outcome qoidalari:

- `TP`: WIN sifatida hisoblanadi
- `SL`: LOSS sifatida hisoblanadi
- `AMBIGUOUS`: alohida sanaladi, win rate denominatoridan chiqariladi
- `OPEN` / `PENDING`: skip qilinadi

`data/backtest_results.json` metrikalari: total, win, loss, ambiguous, open, win_rate, avg_pnl_pct, avg_confidence_win/loss, best/worst ticker, timeframe va pattern bo'yicha breakdown.

## Auto-Retraining

Bot har siklda `feedback_log.csv` row sonini tekshiradi. Oxirgi retrain paytidagi feedback soni `data/training_metrics.json`dagi `last_feedback_count` maydonida saqlanadi.

`AUTO_RETRAIN_FEEDBACK_STEP` miqdorida yangi feedback yig'ilsa:

- training pipeline ishga tushadi
- F1-score oldingi eng yaxshi F1dan yuqori bo'lsa `model.joblib` va `data/threshold.txt` yangilanadi
- Telegramga `Model yangilandi` xabari yuboriladi
- F1 yaxshilanmasa model fayli o'zgarmaydi, faqat log va `training_metrics.json` yangilanadi

Training tugaganda:

- `model.joblib` yangilanadi
- ishlatilgan fayllar va metrikalar `data/training_metrics.json` ichiga yoziladi
- `signals.csv` / `signals.log` bo'lsa `data/backtest_results.json` ichiga signal history summary yoziladi
- `data/threshold.txt` faqat yangi F1-score oldingi trainingdan yaxshi bo'lsa yangilanadi

## Threshold

Runtime threshold `data/threshold.txt`dan o'qiladi. Fayl yo'q yoki buzilgan bo'lsa `DEFAULT_THRESHOLD` ishlatiladi. Training paytida threshold precision-recall curve bo'yicha hisoblanadi, `THRESHOLD_MIN/MAX` oralig'iga clamp qilinadi va faqat F1-score yaxshilansa saqlanadi. Bot ish paytida so'nggi yopilgan signallar winrateiga qarab thresholdni kuniga bir marta kichik qadam bilan ham sozlay oladi.

## Deploy

### Railway

Root fayllar:

- `Procfile`
- `runtime.txt`

Worker komandasi:

```text
worker: env PYTHONPATH=src python -m trade_ai.app.watch_best
```

Railway variables:

- `BOT_TOKEN`
- `CHAT_ID`
- `PYTHONPATH=src`
- `TEST_MODE=False`
- `DEFAULT_THRESHOLD=0.60`
- `THRESHOLD_MIN=0.40`
- `THRESHOLD_MAX=0.75`
- `SLEEP_SEC=60`

Railway filesystem ephemeral: `data/signals_history.db`, cache va logs deploy/rebuilddan keyin saqlanmasligi mumkin. Doimiy statistika kerak bo'lsa SQLite o'rniga tashqi DB ulang.

### systemd

Template: [deploy/systemd/trading-bot.service](deploy/systemd/trading-bot.service)

```bash
sudo cp deploy/systemd/trading-bot.service /etc/systemd/system/trading-bot.service
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
sudo systemctl status trading-bot
```

### crontab va logrotate

- [deploy/crontab/trading-bot.cron](deploy/crontab/trading-bot.cron)
- [deploy/logrotate/trading-bot](deploy/logrotate/trading-bot)

## Saqlanadigan Fayllar

- `model.joblib`: ML model
- `data/patterns.csv`: asosiy training dataset
- `data/patterns_bulk.csv`: ixtiyoriy bulk training dataset
- `feedback_log.csv`: ixtiyoriy feedback training dataset
- `data/pending_feedback.json`: Telegram feedback bosilguncha signal feature snapshotlari
- `signals.csv` / `signals.log`: ixtiyoriy real signal tarixi
- `data/threshold.txt`: aktiv probability threshold
- `data/training_metrics.json`: oxirgi training metrikalari va ishlatilgan fayllar
- `data/backtest_results.json`: signal history summary
- `data/watchlist.txt`: production tickerlar
- `data/signals_history.db`: SQLite signal tarixi
- `data/watch_state.json`: runtime state
- `data/yf_cache/`: market data cache
- `data/logs/`: runtime loglar
