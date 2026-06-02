from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from trade_ai.config import settings
from trade_ai.core.data_loader import fetch_entry_atr_rsi, read_watchlist
from trade_ai.core.strategy import Prediction, calc_sl_tp, get_model_status, predict_market, read_threshold, test_log_line
from trade_ai.services.db import (
    get_meta,
    init_db,
    insert_signal,
    set_meta,
    stats_summary,
    update_open_signal_outcomes,
    win_rate_global,
    win_rate_ticker,
)
from trade_ai.services.telegram import (
    TelegramLogHandler,
    build_live_status_message,
    build_model_status_message,
    build_signal_message,
    build_stats_message,
    build_validation_message,
    edit_message,
    poll_updates,
    send_control_panel,
    send_message,
    send_message_with_id,
    send_signal,
)
from trade_ai.services.validator import validate_pending
from trade_ai.utils.helpers import clamp, is_finite
from trade_ai.utils.logger import setup_logger

logger = setup_logger("trade_ai.watch_best")
if not any(isinstance(handler, TelegramLogHandler) for handler in logger.handlers):
    telegram_handler = TelegramLogHandler(level=getattr(logging, settings.TELEGRAM_LOG_LEVEL, logging.WARNING))
    telegram_handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logger.addHandler(telegram_handler)


def load_state() -> dict:
    if settings.WATCH_STATE_PATH.exists():
        try:
            return json.loads(settings.WATCH_STATE_PATH.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    try:
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        settings.WATCH_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.warning("State save failed")


def write_threshold(value: float) -> None:
    settings.THRESHOLD_PATH.write_text(
        f"{clamp(value, settings.THRESHOLD_MIN, settings.THRESHOLD_MAX):.4f}",
        encoding="utf-8",
    )


def maybe_adjust_threshold(data_error_ratio: Optional[float] = None) -> None:
    today = datetime.now().date().isoformat()
    if get_meta("last_adj_date", "") == today:
        return
    wins, total = win_rate_global(n=30)
    if total < 10:
        return
    threshold = read_threshold()
    wr = wins / max(1, total)
    new_threshold = threshold
    if wr < 0.45:
        if data_error_ratio is not None and data_error_ratio > 0.50:
            set_meta("last_adj_date", today)
            logger.warning(
                "THRESH auto-tune skipped: data_error_ratio=%.0f%% threshold=%.2f winrate=%d%% over %d",
                data_error_ratio * 100,
                threshold,
                int(wr * 100),
                total,
            )
            return
        new_threshold += 0.02
    elif wr > 0.60:
        new_threshold -= 0.01
    new_threshold = clamp(new_threshold, settings.THRESHOLD_MIN, settings.THRESHOLD_MAX)
    if abs(new_threshold - threshold) >= 0.0009:
        write_threshold(new_threshold)
        set_meta("last_adj_date", today)
        logger.info("THRESH auto-tune %.2f -> %.2f (winrate=%d%% over %d)", threshold, new_threshold, int(wr * 100), total)


def pick_best(predictions: list[Prediction]) -> Optional[Prediction]:
    candidates = [
        prediction
        for prediction in predictions
        if ("BUY" in prediction.signal or "SELL" in prediction.signal)
        and "HOLD" not in prediction.signal
        and "CONFLICT" not in prediction.signal
        and is_finite(prediction.p)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.p + (0.05 if "STRONG_" in item.signal else 0.0)), reverse=True)
    return candidates[0]


def pick_fallback_best(predictions: list[Prediction]) -> Optional[Prediction]:
    candidates = [
        prediction
        for prediction in predictions
        if prediction.reason != "data_error"
        and is_finite(prediction.p)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.p, reverse=True)
    best = candidates[0]
    forced_signal = best.signal
    if "BUY" not in forced_signal and "SELL" not in forced_signal:
        forced_signal = "BUY" if best.side == "BUY" else "SELL"
    return Prediction(
        ticker=best.ticker,
        signal=forced_signal,
        p=best.p,
        threshold=best.threshold,
        side=best.side,
        reason="forced_test_signal",
        err=best.err,
        entry=best.entry,
        atr=best.atr,
        sl=best.sl,
        tp=best.tp,
        squeeze=best.squeeze,
        breakout=best.breakout,
        h1=best.h1,
        d1=best.d1,
    )


def winrate_text(ticker: str) -> str:
    wins, total = win_rate_ticker(ticker, n=10)
    if total < 3:
        return "Win Rate (last 10): N/A"
    pct = int(round(100 * wins / max(1, total)))
    return f"Win Rate (last 10): {wins}/{total} ({pct}%)"


def log_prediction_details(now_str: str, predictions: list[Prediction]) -> None:
    reason_counts: dict[str, int] = {}
    for prediction in predictions:
        reason_counts[prediction.reason] = reason_counts.get(prediction.reason, 0) + 1
        logger.info("%s | [%s] data=%s", now_str, prediction.ticker, "FAIL" if prediction.reason == "data_error" else "OK")
        if settings.TEST_MODE:
            logger.info("%s | %s", now_str, test_log_line(prediction))
            if prediction.reason == "data_error":
                logger.info("%s | [REJECT] %s -> DATA ERROR", now_str, prediction.ticker)
            elif prediction.reason == "low_proba":
                logger.info("%s | [REJECT] %s -> LOW PROBA", now_str, prediction.ticker)
            elif prediction.signal == "HOLD":
                logger.info("%s | [REJECT] %s -> %s", now_str, prediction.ticker, prediction.reason.upper())
            else:
                logger.info("%s | [PASS] %s -> %s p=%.2f", now_str, prediction.ticker, prediction.signal, prediction.p)
        logger.info(
            "%s | %s | data=%s p=%.2f th=%.2f signal=%s reject=%s err=%s",
            now_str,
            prediction.ticker,
            "fail" if prediction.reason == "data_error" else "ok",
            prediction.p,
            prediction.threshold,
            prediction.signal,
            prediction.reason,
            prediction.err or "-",
        )
    if reason_counts:
        summary = ", ".join(f"{key}={value}" for key, value in sorted(reason_counts.items()))
        logger.info("%s | REASON_SUMMARY | %s", now_str, summary)


def update_live_status(message_id: Optional[int], tf_label: str, cycle_no: int, step: str, detail: str, last_signal: str = "-", next_sleep_sec: Optional[int] = None) -> None:
    if not message_id:
        return
    text = build_live_status_message(
        step=step,
        tf_label=tf_label,
        cycle_no=cycle_no,
        detail=detail,
        last_signal=last_signal,
        next_sleep_sec=next_sleep_sec,
    )
    code, response = edit_message(message_id, text)
    if code not in (0, 200):
        logger.warning("Live status edit failed: %s", response)


def maybe_send_stats(started_at: datetime, requests_count: int) -> None:
    if requests_count <= 0:
        return
    total_signals, wins, total_closed = stats_summary()
    text = build_stats_message(started_at, total_signals, wins, total_closed)
    for _ in range(requests_count):
        send_message(text)


def maybe_send_model_status(requests_count: int) -> None:
    if requests_count <= 0:
        return
    text = build_model_status_message(get_model_status())
    for _ in range(requests_count):
        send_message(text)


def sltp_valid(entry: float, sl: float, tp: float, side: str) -> bool:
    side = (side or "").upper()
    if side == "BUY":
        return sl < entry < tp
    if side == "SELL":
        return tp < entry < sl
    return False


def main() -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    model_status = get_model_status()
    if model_status["loaded"]:
        logger.info(
            "MODEL STATUS | loaded=YES | type=%s | size_bytes=%d | path=%s",
            model_status["model_type"],
            model_status["size_bytes"],
            model_status["path"],
        )
    else:
        raise RuntimeError(
            "Model load failed: "
            f"path={model_status['path']} exists={model_status['exists']} error={model_status['error']}"
        )

    total_scans = 0
    data_errors = 0
    low_proba_skips = 0
    model_errors = 0
    signals_sent = 0
    cycle_no = 0
    sent_signals: set[str] = set()
    started_at = datetime.now()
    set_meta("bot_started_at", started_at.isoformat())

    state = load_state()
    tf_label = (state.get("tf_label") or settings.DEFAULT_TF_LABEL).upper()
    if tf_label not in settings.TF_MAP:
        tf_label = settings.DEFAULT_TF_LABEL
    last_key = state.get("last_key", "")
    last_time = float(state.get("last_time", 0.0) or 0.0)
    last_day = state.get("last_day")
    update_offset = int(state.get("upd_offset", 0) or 0)
    last_signal_label = "-"

    logger.info("BEST WATCH started. TF=%s", tf_label)
    send_control_panel(tf_label)
    status_code, status_message_id, _ = send_message_with_id(
        build_live_status_message(
            step="Ishga tushdi",
            tf_label=tf_label,
            cycle_no=cycle_no,
            detail="Bot inicializatsiya qilindi",
            last_signal=last_signal_label,
            next_sleep_sec=settings.SLEEP_SEC,
        )
    )
    if status_code != 200:
        logger.warning("Live status init failed")

    while True:
        try:
            cycle_no += 1
            now_dt = datetime.now()
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            today = now_dt.date().isoformat()

            update_offset, events = poll_updates(update_offset, settings.TF_MAP)
            maybe_send_stats(started_at, events.stats_requests)
            maybe_send_model_status(events.model_requests)
            if events.selected_tf and events.selected_tf != tf_label:
                tf_label = events.selected_tf
                logger.info("%s | TF switched to %s", now_str, tf_label)
                send_control_panel(tf_label)

            if last_day != today:
                logger.info("%s | NEW DAY session: reset duplicate cache", now_str)
                last_day = today
                sent_signals.clear()
                last_key = ""
                last_time = 0.0

            update_live_status(status_message_id, tf_label, cycle_no, "Skanerlanmoqda", "Ochiq signallar tekshirilyapti", last_signal_label)
            update_open_signal_outcomes(limit=50)
            validation_results = validate_pending()
            for result in validation_results:
                send_message(
                    build_validation_message(
                        ticker=str(result["ticker"]),
                        side=str(result["side"]),
                        outcome=str(result["outcome"]),
                        pnl_pct=float(result["pnl"]),
                        price_open=float(result["price_open"]),
                        price_now=float(result["price_now"]),
                        confidence=float(result["p"]),
                    )
                )

            tickers = settings.TEST_TICKERS if settings.TEST_MODE else read_watchlist()
            if settings.TEST_MODE:
                logger.info("%s | [TEST MODE] Using fixed tickers: %s", now_str, tickers)
            update_live_status(
                status_message_id,
                tf_label,
                cycle_no,
                "Analiz qilinmoqda",
                f"{len(tickers)} ta ticker baholanmoqda",
                last_signal_label,
            )
            predictions = predict_market(tf_label, tickers)
            log_prediction_details(now_str, predictions)

            total_scans += len(predictions)
            cycle_data_errors = sum(1 for item in predictions if item.reason == "data_error")
            cycle_low_proba = sum(1 for item in predictions if item.reason == "low_proba")
            cycle_model_errors = sum(1 for item in predictions if item.reason == "model_error")
            data_errors += cycle_data_errors
            low_proba_skips += cycle_low_proba
            model_errors += cycle_model_errors
            maybe_adjust_threshold(data_error_ratio=(cycle_data_errors / max(1, len(predictions))) if predictions else None)
            if cycle_model_errors:
                logger.warning(
                    "%s | MODEL HEALTH | model_error=%d/%d",
                    now_str,
                    cycle_model_errors,
                    len(predictions),
                )

            if cycle_data_errors >= 5:
                logger.error(
                    "%s | [DATA FAILURE MODE] data_error=%d/%d | tickers=%s",
                    now_str,
                    cycle_data_errors,
                    len(predictions),
                    ",".join(item.ticker for item in predictions if item.reason == "data_error"),
                )
                update_live_status(
                    status_message_id,
                    tf_label,
                    cycle_no,
                    "Data Failure Mode",
                    f"{cycle_data_errors} ta ticker data bermadi, signal to'xtatildi",
                    last_signal_label,
                    next_sleep_sec=settings.SLEEP_SEC,
                )
                save_state(
                    {
                        "tf_label": tf_label,
                        "last_key": last_key,
                        "last_time": last_time,
                        "last_day": last_day,
                        "upd_offset": update_offset,
                    }
                )
                time.sleep(settings.SLEEP_SEC)
                continue

            best = pick_best(predictions)
            if best and settings.TEST_MODE:
                logger.info("%s | [TEST MODE] BEST candidate: %s %s %.2f", now_str, best.ticker, best.signal, best.p)
            if not best:
                signal_count = sum(1 for item in predictions if ("BUY" in item.signal or "SELL" in item.signal))
                detail = "Mos signal topilmadi"
                if settings.TEST_MODE and settings.FORCE_SIGNAL_IN_TEST:
                    logger.info("%s | [TEST MODE] No signal -> forcing fallback", now_str)
                    best = pick_fallback_best(predictions)
                    if best:
                        logger.info("%s | [TEST MODE] FORCE BEST: %s %s %.2f", now_str, best.ticker, best.signal, best.p)
                if predictions and cycle_data_errors == len(predictions):
                    logger.warning(
                        "%s | DATA ERROR MODE | data_error=%d/%d | tickers=%s",
                        now_str,
                        cycle_data_errors,
                        len(predictions),
                        ",".join(item.ticker for item in predictions),
                    )
                    detail = f"DATA ERROR MODE: {cycle_data_errors}/{len(predictions)} tickerda data yo'q"
                else:
                    logger.info(
                        "%s | BEST=NONE (all HOLD) | data_error=%d low_proba=%d signal=%d",
                        now_str,
                        cycle_data_errors,
                        cycle_low_proba,
                        signal_count,
                    )
                if best is None:
                    if settings.TEST_MODE:
                        logger.info("%s | [TEST MODE] No signal -> forcing fallback failed", now_str)
                    update_live_status(status_message_id, tf_label, cycle_no, "Yakunlandi", detail, last_signal_label, next_sleep_sec=settings.SLEEP_SEC)
                    save_state(
                        {
                            "tf_label": tf_label,
                            "last_key": last_key,
                            "last_time": last_time,
                            "last_day": last_day,
                            "upd_offset": update_offset,
                        }
                    )
                    time.sleep(settings.SLEEP_SEC)
                    continue

            side = (best.side or "").upper()
            if side not in ("BUY", "SELL"):
                logger.warning("%s | BEST=%s INVALID_SIDE=%s", now_str, best.ticker, best.side)
                update_live_status(status_message_id, tf_label, cycle_no, "Yakunlandi", f"{best.ticker} uchun side noto'g'ri", last_signal_label, next_sleep_sec=settings.SLEEP_SEC)
                time.sleep(settings.SLEEP_SEC)
                continue

            interval, period = settings.TF_MAP.get(tf_label, settings.TF_MAP[settings.DEFAULT_TF_LABEL])
            entry, atr14, rsi = fetch_entry_atr_rsi(best.ticker, interval=interval, period=period)
            if entry is None or atr14 is None or atr14 <= 0:
                logger.warning("%s | BEST=%s data_error (no ATR/entry)", now_str, best.ticker)
                update_live_status(status_message_id, tf_label, cycle_no, "Yakunlandi", f"{best.ticker} uchun market data yetarli emas", last_signal_label, next_sleep_sec=settings.SLEEP_SEC)
                time.sleep(settings.SLEEP_SEC)
                continue

            sl, tp = calc_sl_tp(entry, atr14, side)
            if not sltp_valid(entry, sl, tp, side):
                logger.warning("%s | invalid_levels ticker=%s side=%s entry=%.4f sl=%.4f tp=%.4f", now_str, best.ticker, side, entry, sl, tp)
                update_live_status(status_message_id, tf_label, cycle_no, "Yakunlandi", f"{best.ticker} uchun SL/TP noto'g'ri", last_signal_label, next_sleep_sec=settings.SLEEP_SEC)
                time.sleep(settings.SLEEP_SEC)
                continue

            dedupe_key = f"{best.ticker}:{side}:{tf_label}"
            if dedupe_key in sent_signals:
                logger.info("%s | DUPLICATE skip (set) %s", now_str, dedupe_key)
                update_live_status(status_message_id, tf_label, cycle_no, "Yakunlandi", "Takroriy signal yuborilmadi", last_signal_label, next_sleep_sec=settings.SLEEP_SEC)
                time.sleep(settings.SLEEP_SEC)
                continue
            if dedupe_key == last_key and (time.time() - last_time) < settings.DUPLICATE_TTL_SEC:
                logger.info("%s | DUPLICATE skip (ttl) %s", now_str, dedupe_key)
                update_live_status(status_message_id, tf_label, cycle_no, "Yakunlandi", "TTL ichida bir xil signal qayta yuborilmadi", last_signal_label, next_sleep_sec=settings.SLEEP_SEC)
                time.sleep(settings.SLEEP_SEC)
                continue

            update_live_status(status_message_id, tf_label, cycle_no, "Saqlanmoqda", f"{best.ticker} signal Telegram va bazaga yozilyapti", last_signal_label)
            signal_id = str(uuid.uuid4())[:8]
            message = build_signal_message(
                ticker=best.ticker,
                signal=best.signal,
                confidence=best.p,
                now_dt=now_dt,
                entry=entry,
                sl=sl,
                tp=tp,
                tf_label=tf_label,
                winrate_line=winrate_text(best.ticker),
                rsi=rsi,
            )
            code, response = send_signal(message, signal_id, best.ticker)
            logger.info("%s | telegram_status=%s", now_str, code)
            logger.info("%s | BEST=%s %s p=%.2f", now_str, best.ticker, best.signal, best.p)
            if code == 200:
                signals_sent += 1
                sent_signals.add(dedupe_key)
                insert_signal(
                    sig_id=signal_id,
                    ts=int(time.time()),
                    ticker=best.ticker,
                    side=side,
                    tf_label=tf_label,
                    interval=interval,
                p=float(best.p),
                entry=float(entry),
                sl=float(sl),
                tp=float(tp),
                price_at_signal=float(entry),
            )
                last_signal_label = f"{best.ticker} {best.signal}"
            else:
                logger.warning("%s | notifier_error=%s", now_str, response)

            last_key = dedupe_key
            last_time = time.time()
            save_state(
                {
                    "tf_label": tf_label,
                    "last_key": last_key,
                    "last_time": last_time,
                    "last_day": last_day,
                    "upd_offset": update_offset,
                }
            )
            update_live_status(
                status_message_id,
                tf_label,
                cycle_no,
                "Yakunlandi",
                f"Cycle tugadi. Sent={signals_sent}, scans={total_scans}",
                last_signal_label,
                next_sleep_sec=settings.SLEEP_SEC,
            )
            time.sleep(settings.SLEEP_SEC)
        except KeyboardInterrupt:
            send_message(
                "<b>BOT STOPPED</b>\n"
                f"TOTAL_SCANS={total_scans}\n"
                f"DATA_ERRORS={data_errors}\n"
                f"LOW_PROBA_SKIPS={low_proba_skips}\n"
                f"MODEL_ERRORS={model_errors}\n"
                f"SIGNALS_SENT={signals_sent}\n"
            )
            break
        except Exception as exc:
            logger.exception("Main loop error: %r", exc)
            update_live_status(
                status_message_id,
                tf_label,
                cycle_no,
                "Xatolik",
                f"{type(exc).__name__}: {exc}",
                last_signal_label,
                next_sleep_sec=10,
            )
            time.sleep(10)


if __name__ == "__main__":
    main()

