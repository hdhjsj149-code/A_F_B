"""
==============================================================
شغّل هذا الملف مرة واحدة بس، بعد ما ترفع البوت على Render
Run this file ONCE, after your bot is deployed on Render
==============================================================
يخبر تيلجرام: "ابعت كل التحديثات الجديدة لهذا الرابط"
Tells Telegram: "send all new updates to this URL"

طريقة التشغيل / how to run:
    python setup_webhook.py
"""
import telegram_api
from config import RENDER_EXTERNAL_URL, WEBHOOK_SECRET

if not RENDER_EXTERNAL_URL:
    raise SystemExit("❌ حط RENDER_EXTERNAL_URL بملف .env أول (رابط موقعك على Render)")

full_url = f"{RENDER_EXTERNAL_URL}/webhook/{WEBHOOK_SECRET}"
result = telegram_api.set_webhook(full_url)
print("النتيجة:", result)
