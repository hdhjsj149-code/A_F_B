"""
==============================================================
غلاف Telegram API - نداءات مباشرة بسيطة (requests) بدون مكتبة
Telegram API wrapper - plain requests calls, no heavy async lib
==============================================================
اخترنا هذا الأسلوب (بدل python-telegram-bot) لأنه أبسط وأثبت
داخل تطبيق Flask متزامن (sync) يشتغل على Render بنظام webhook
Chosen over python-telegram-bot because it's simpler and more
stable inside a sync Flask app running in webhook mode on Render
"""
import requests

from config import TELEGRAM_BOT_TOKEN

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _call(method: str, payload: dict | None = None, files=None):
    try:
        resp = requests.post(f"{API_BASE}/{method}", data=payload, files=files, timeout=20)
        return resp.json()
    except requests.RequestException:
        return {"ok": False}


def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call("sendMessage", payload)


def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call("editMessageText", payload)


def answer_callback_query(callback_query_id, text=None, show_alert=False):
    payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
    if text:
        payload["text"] = text
    return _call("answerCallbackQuery", payload)


def get_file_path(file_id: str) -> str | None:
    result = _call("getFile", {"file_id": file_id})
    if result.get("ok"):
        return result["result"]["file_path"]
    return None


def download_file(file_path: str) -> bytes | None:
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException:
        return None


def set_webhook(url: str):
    return _call("setWebhook", {"url": url})
