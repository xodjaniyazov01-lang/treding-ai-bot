# Trade AI

Minimal signal bot focused on a single production runtime:

`python -m trade_ai.app.watch_best`

## Structure

`src/trade_ai/app/`
- `watch_best.py`: live watcher and Telegram notification loop
- `trainer.py`: model training entrypoint

`src/trade_ai/core/`
- `data_loader.py`: watchlist IO and market data loading
- `model.py`: training pipeline and threshold selection
- `strategy.py`: market scoring and signal generation

`src/trade_ai/services/`
- `db.py`: SQLite signal storage
- `telegram.py`: Telegram API and message builders

`src/trade_ai/utils/`
- `logger.py`: logger bootstrap
- `helpers.py`: small shared helpers

## Run

PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m trade_ai.app.watch_best
```

Train model:

```powershell
$env:PYTHONPATH = "src"
python -m trade_ai.app.trainer
```

## Data files

Runtime files live in `data/`:

- `patterns.csv`
- `watchlist.txt`
- `threshold.txt`
- `watch_state.json`
- `signals_history.db`
- `yf_cache/`
