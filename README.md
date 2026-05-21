# trading-ai-bot

Signal bot entrypoint:

```powershell
$env:PYTHONPATH = "src"
py -3.14 -m trade_ai.app.watch_best
```

## Environment

Create `.env` from `.env.example` and fill in Telegram credentials.

Key runtime flags:

- `TEST_MODE=False` for production
- `TEST_TICKERS=` only used when `TEST_MODE=True`
- `DEFAULT_THRESHOLD=0.60`
- `SLEEP_SEC=60`

## Production

### systemd

Template file: [deploy/systemd/trading-bot.service](deploy/systemd/trading-bot.service)

Typical commands:

```bash
sudo cp deploy/systemd/trading-bot.service /etc/systemd/system/trading-bot.service
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
sudo systemctl status trading-bot
```

Recommended for Linux VPS. The service is configured with:

- `Restart=on-failure`
- `RestartSec=60`
- stdout -> `data/logs/bot.log`
- stderr -> `data/logs/bot.err.log`

After a reboot, `systemctl enable` ensures the bot starts automatically.

### crontab

Template file: [deploy/crontab/trading-bot.cron](deploy/crontab/trading-bot.cron)

Use this when you want scheduled launches instead of a long-running service.

The cron template uses `flock` so two overlapping runs do not start at the same time.

### Log rotation

Template file: [deploy/logrotate/trading-bot](deploy/logrotate/trading-bot)

Runtime logs are written to:

- `data/logs/bot.log`
- `data/logs/bot.err.log`

The Python logger also uses rotating file handlers controlled by:

- `LOG_MAX_BYTES`
- `LOG_BACKUP_COUNT`

## Production Runbook

Start the production bot:

```bash
sudo systemctl start trading-bot
```

Check service status:

```bash
sudo systemctl status trading-bot
```

Follow logs:

```bash
tail -f data/logs/bot.log
tail -f data/logs/bot.err.log
```

Check the active threshold:

```bash
cat data/threshold.txt
```

Current target threshold is `0.60`. Review date: `2026-05-08`.

## Railway

Root deploy files:

- `Procfile`
- `runtime.txt`

Railway should run the worker process, not a web process:

```text
worker: env PYTHONPATH=src python -m trade_ai.app.watch_best
```

Set these Railway Variables:

- `BOT_TOKEN`
- `CHAT_ID`
- `TEST_MODE=False`
- `DEFAULT_THRESHOLD=0.60`
- `THRESHOLD_MAX=0.75`
- `PYTHONPATH=src`
- `SLEEP_SEC=60`

Notes:

- The current code reads `BOT_TOKEN` and `CHAT_ID`, not `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`.
- Railway filesystem is ephemeral. `data/signals_history.db` will not be durable across fresh deploys or rebuilds.
- For now this is acceptable only if Telegram delivery is the primary requirement and SQLite persistence is optional.
- If DB persistence becomes required, move signal storage to Railway Postgres or another external database.

## Training

```powershell
$env:PYTHONPATH = "src"
py -3.14 -m trade_ai.app.trainer
```

## Storage

- `data/signals_history.db`: SQLite signal history
- `data/threshold.txt`: active probability threshold
- `data/watchlist.txt`: production ticker list
- `data/watch_state.json`: runtime state
- `data/yf_cache/`: cached market data
- `data/logs/`: runtime logs
