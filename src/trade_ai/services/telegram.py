from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Dict, Optional, Tuple

import requests

from trade_ai.config import settings


@dataclass
class BotEvents:
    selected_tf: Optional[str] = None
    stats_requests: int = 0


def tg_api(method: str, data: dict) -> Tuple[int, str]:
    if not settings.BOT_TOKEN:
        return 0, "missing BOT_TOKEN"
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}"
    try:
        response = requests.post(url, json=data, timeout=settings.TELEGRAM_TIMEOUT_SEC)
        return response.status_code, response.text[:500]
    except Exception as exc:
        return 0, repr(exc)


def tg_api_json(method: str, data: dict) -> Tuple[int, dict]:
    if not settings.BOT_TOKEN:
        return 0, {"ok": False, "description": "missing BOT_TOKEN"}
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}"
    try:
        response = requests.post(url, json=data, timeout=settings.TELEGRAM_TIMEOUT_SEC)
        try:
            body = response.json()
        except Exception:
            body = {"ok": False, "description": response.text[:500]}
        return response.status_code, body
    except Exception as exc:
        return 0, {"ok": False, "description": repr(exc)}


def send_message(text: str, reply_markup: Optional[dict] = None, parse_mode: str = "HTML") -> Tuple[int, str]:
    payload = {"chat_id": settings.CHAT_ID, "text": text, "parse_mode": parse_mode}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return tg_api("sendMessage", payload)


def send_message_with_id(text: str, reply_markup: Optional[dict] = None, parse_mode: str = "HTML") -> Tuple[int, Optional[int], str]:
    payload = {"chat_id": settings.CHAT_ID, "text": text, "parse_mode": parse_mode}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    code, body = tg_api_json("sendMessage", payload)
    message_id = None
    if body.get("ok"):
        try:
            message_id = int(body["result"]["message_id"])
        except Exception:
            message_id = None
    return code, message_id, str(body)[:500]


def edit_message(message_id: int, text: str, reply_markup: Optional[dict] = None, parse_mode: str = "HTML") -> Tuple[int, str]:
    payload = {
        "chat_id": settings.CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return tg_api("editMessageText", payload)


def answer_callback(callback_query_id: str, text: str = "") -> Tuple[int, str]:
    return tg_api("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})


def tf_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "M5", "callback_data": "TF:M5"},
                {"text": "M15", "callback_data": "TF:M15"},
                {"text": "H1", "callback_data": "TF:H1"},
                {"text": "H4", "callback_data": "TF:H4"},
            ],
        ]
    }


def poll_updates(offset: int, valid_timeframes: Dict[str, tuple]) -> Tuple[int, BotEvents]:
    events = BotEvents()
    if not settings.BOT_TOKEN:
        return offset, events
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getUpdates"
    params = {
        "timeout": 0,
        "offset": offset,
        "allowed_updates": ["callback_query", "message"],
    }
    try:
        response = requests.get(url, params=params, timeout=settings.TELEGRAM_POLL_TIMEOUT_SEC)
        data = response.json()
    except Exception:
        return offset, events
    if not isinstance(data, dict) or not data.get("ok"):
        return offset, events
    for update in data.get("result", []):
        try:
            update_id = int(update.get("update_id"))
            offset = max(offset, update_id + 1)
        except Exception:
            continue

        callback = update.get("callback_query") or {}
        callback_id = callback.get("id")
        callback_data = (callback.get("data") or "").strip()
        if callback_data.startswith("TF:"):
            tf_label = callback_data.split(":", 1)[1].strip().upper()
            if tf_label in valid_timeframes:
                events.selected_tf = tf_label
                if callback_id:
                    answer_callback(callback_id, f"Timeframe set: {tf_label}")
            continue
        if callback_data.startswith("WIN:") or callback_data.startswith("LOSS:"):
            if callback_id:
                answer_callback(callback_id, "Outcome noted")
            continue

        message = update.get("message") or {}
        text = (message.get("text") or "").strip().lower()
        if text == "/stats":
            events.stats_requests += 1
    return offset, events


def send_control_panel(tf_label: str) -> Tuple[int, str]:
    text = (
        "<b>Trade AI Control Panel</b>\n"
        f"Current TF: <b>{escape(tf_label)}</b>\n"
        "Commands: <code>/stats</code>\n\n"
        "Tap to switch timeframe:"
    )
    return send_message(text, reply_markup=tf_keyboard())


def _signal_theme(signal: str) -> Tuple[str, str]:
    upper = signal.upper()
    if "EXPLOSIVE" in upper:
        return "EXPLOSIVE <b>PREMIUM SIGNAL</b>", "Volatility squeeze breakout"
    if "STRONG" in upper:
        return "STRONG <b>PREMIUM SIGNAL</b>", "Trend confirmation active"
    return "SIGNAL <b>PREMIUM SETUP</b>", "Best current setup"


def confidence_bar(confidence: float, slots: int = 10) -> str:
    pct = max(0, min(100, int(round(float(confidence) * 100))))
    filled = max(0, min(slots, int(round(pct / 10))))
    return f"{'#' * filled}{'-' * (slots - filled)} {pct}%"


def tradingview_url(ticker: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol={escape((ticker or '').strip().upper())}"


def build_signal_message(
    ticker: str,
    signal: str,
    confidence: float,
    now_dt: datetime,
    entry: float,
    sl: float,
    tp: float,
    tf_label: str,
    winrate_line: str,
    rsi: Optional[float] = None,
) -> str:
    header, setup = _signal_theme(signal)
    lines = [
        header,
        "",
        f"<b>Symbol:</b> <code>{escape(ticker)}</code>",
        f"<b>Signal:</b> <b>{escape(signal)}</b>",
        f"<b>Confidence:</b> {confidence_bar(confidence)}",
        f"<b>Time:</b> <code>{escape(now_dt.strftime('%Y-%m-%d %H:%M:%S'))}</code>",
        f"<b>Timeframe:</b> <b>{escape(tf_label)}</b>",
        f"<b>Setup:</b> {escape(setup)}",
    ]
    if rsi is not None:
        lines.append(f"<b>RSI:</b> <code>{rsi:.1f}</code>")
    lines.append(f"<b>{escape(winrate_line)}</b>")
    lines.extend(
        [
            "",
            f"<b>Entry:</b> <code>{entry:.4f}</code>",
            f"<b>Stop Loss:</b> <code>{sl:.4f}</code>",
            f"<b>Take Profit:</b> <code>{tp:.4f}</code>",
        ]
    )
    return "\n".join(lines)


def build_live_status_message(step: str, tf_label: str, cycle_no: int, detail: str, last_signal: str = "-", next_sleep_sec: Optional[int] = None) -> str:
    lines = [
        "<b>Trade AI Live Status</b>",
        "",
        f"Stage: <b>{escape(step)}</b>",
        f"TF: <b>{escape(tf_label)}</b>",
        f"Cycle: <code>{cycle_no}</code>",
        f"Last signal: <code>{escape(last_signal)}</code>",
        f"Detail: {escape(detail)}",
    ]
    if next_sleep_sec is not None:
        lines.append(f"Next scan: <code>{int(next_sleep_sec)}s</code>")
    lines.append(f"Updated: <code>{escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</code>")
    return "\n".join(lines)


def build_stats_message(started_at: datetime, total_signals: int, wins: int, total_closed: int) -> str:
    uptime_text = str(datetime.now() - started_at).split(".", 1)[0]
    win_rate = int(round((wins / max(1, total_closed)) * 100)) if total_closed else 0
    return (
        "<b>Trade AI Statistics</b>\n\n"
        f"<b>Uptime:</b> <code>{escape(uptime_text)}</code>\n"
        f"<b>Total signals:</b> <code>{total_signals}</code>\n"
        f"<b>Win rate:</b> <code>{wins}/{total_closed} ({win_rate}%)</code>\n"
    )


def build_validation_message(
    ticker: str,
    side: str,
    outcome: str,
    pnl_pct: float,
    price_open: float,
    price_now: float,
    confidence: float,
) -> str:
    outcome_upper = (outcome or "").upper()
    icon = "✅" if outcome_upper == "WIN" else "❌"
    pnl_icon = "📈" if pnl_pct > 0 else "📉"
    cash_icon = "💰" if pnl_pct > 0 else "💸"
    sign = "+" if pnl_pct > 0 else ""
    return (
        f"{icon} {escape(outcome_upper)}: {escape((ticker or '').upper())} {escape((side or '').upper())}\n\n"
        f"{pnl_icon} {sign}{pnl_pct:.1f}% (1 soat)\n"
        f"{cash_icon} ${price_open:.2f} -> ${price_now:.2f}\n"
        f"🎯 p={confidence:.2f}"
    )


def send_signal(text: str, signal_id: str, ticker: str) -> Tuple[int, str]:
    payload = {
        "chat_id": settings.CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "WIN", "callback_data": f"WIN:{signal_id}"},
                    {"text": "LOSS", "callback_data": f"LOSS:{signal_id}"},
                ],
                [{"text": "TradingView", "url": tradingview_url(ticker)}],
            ]
        },
    }
    return tg_api("sendMessage", payload)


class TelegramLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = escape(self.format(record))
            send_message(f"<b>Trade AI Log</b>\n<code>{text}</code>")
        except Exception:
            return
