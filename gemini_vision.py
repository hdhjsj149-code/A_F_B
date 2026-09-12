"""
==============================================================
وحدة Gemini Vision - يُستخدم حصراً لتحليل صور الشارتات
Gemini Vision module - used EXCLUSIVELY for chart image analysis
==============================================================
نظام تدوير المفاتيح: لو مفتاح رجع خطأ "quota exceeded" أو 429،
نعطّله مؤقتاً (ساعة كاملة) ونجرب اللي بعده تلقائياً
Key rotation: if a key returns a quota/429 error, we disable it
for one hour and automatically try the next key in the list
"""
import base64
from datetime import datetime, timedelta

import requests

import database
from config import GEMINI_API_KEYS, GEMINI_MODEL
from knowledge_base import build_full_prompt

GEMINI_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
)


class NoAvailableKeyError(Exception):
    """كل المفاتيح معطّلة مؤقتاً / all keys are temporarily disabled"""


def _is_key_available(index: int) -> bool:
    disabled_until = database.get_disabled_until(index)
    if not disabled_until:
        return True
    return datetime.utcnow().isoformat() > disabled_until


def _disable_key(index: int, hours: int = 1):
    until = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
    database.disable_key_temporarily(index, until)


def analyze_chart_image(image_bytes: bytes, user_caption: str = "") -> str:
    """
    يجرب كل مفتاح بالترتيب لحد ما يلاقي واحد شغال أو تخلص كلها
    Tries each key in order until one works, or raises if all are exhausted
    """
    if not GEMINI_API_KEYS:
        return "⚠️ ما في مفاتيح Gemini مضافة بالإعدادات (GEMINI_API_KEYS)."

    expert_notes = database.get_expert_notes()
    knowledge_items = database.get_knowledge(limit=80)
    prompt = build_full_prompt(expert_notes, knowledge_items)
    if user_caption:
        prompt += f"\n\nملاحظة من المستخدم مرفقة مع الصورة: {user_caption}"

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    last_error = None
    for index, key in enumerate(GEMINI_API_KEYS):
        if not _is_key_available(index):
            continue
        try:
            resp = requests.post(
                GEMINI_URL_TMPL.format(model=GEMINI_MODEL, key=key),
                json={
                    "contents": [{
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                        ]
                    }]
                },
                timeout=60,
            )
            if resp.status_code == 429:
                # نفدت الكوتة لهذا المفتاح - عطّله وجرب التالي
                # Quota exhausted for this key - disable it and try the next
                _disable_key(index)
                last_error = "quota_exceeded"
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except requests.RequestException as e:
            last_error = str(e)
            continue

    if last_error == "quota_exceeded":
        return "⚠️ كل مفاتيح Gemini المتوفرة وصلت لحد الكوتة المجانية حالياً، جرب بعد شوي."
    return f"⚠️ صار خطأ أثناء تحليل الصورة: {last_error or 'سبب غير معروف'}"
