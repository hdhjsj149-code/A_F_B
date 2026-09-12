# تشغيل البوت على Render بدون VPS

## 1) قاعدة البيانات
أنشئ PostgreSQL على Render، ثم ضع `DATABASE_URL` في Environment Variables.

## 2) المتغيرات الضرورية
ضع:
- `TELEGRAM_BOT_TOKEN`
- `RENDER_EXTERNAL_URL`
- `WEBHOOK_SECRET` (قوي وعشوائي)
- `OWNER_USER_ID=7601281598`
- `TWELVE_DATA_API_KEY` (مفتاح Twelve Data)
- `MARKET_DATA_SOURCE=auto`

`DATABASE_URL` يأتي من Render PostgreSQL.

## 3) Build / Start
Build:
```text
pip install -r requirements.txt
```
Start:
```text
gunicorn app:app
```

## 4) البيانات
في `auto`:
- Forex/Gold: Twelve Data إذا كان المفتاح موجوداً.
- Crypto: Binance public market data.
- MT5: لا يستخدم على Render مباشرة؛ يضاف لاحقاً عبر Read-Only Bridge.
- إذا تعذر Twelve Data أثناء جلب عام، يوجد fallback محافظ إلى Yahoo Finance، لكن الصفقة التاريخية تحفظ مصدرها ولا تخلط المصادر داخل الـsnapshot.

## 5) مهم
لا تضع كلمة مرور MT5 أو API تداول في Render. `TWELVE_DATA_API_KEY` خاص ببيانات السوق فقط.

## 6) Webhook
بعد نجاح Deploy، افتح:
```text
https://YOUR-APP.onrender.com/ping
```
ثم شغّل `setup_webhook.py` من بيئة فيها متغيرات البوت، أو استخدم Telegram webhook setup الموجود بالمشروع.
