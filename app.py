"""
==============================================================
نقطة الدخول الرئيسية - تطبيق Flask بسيط يشغّل كل شي
Main entry point - a simple Flask app that runs everything
==============================================================
مسارين بس:
Just two routes:
  /webhook/<secret>  : تيلجرام يبعث كل تحديث جديد هنا (رسالة/زر)
                       Telegram posts every new update here (msg/button)
  /ping              : الكرون جوب الخارجي يزوره كل 5 دقايق ليبقي البوت صاحي
                       External cron-job.org visits this every 5 min to
                       keep the free Render instance awake
"""
import logging

from flask import Flask, request, jsonify

import database
import handlers
import scheduler
from config import WEBHOOK_SECRET, TELEGRAM_BOT_TOKEN

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("market_bot")

app = Flask(__name__)

# ننشئ جداول قاعدة البيانات مرة وحدة عند إقلاع السيرفر
# Create DB tables once when the server boots
database.init_db()


@app.route("/", methods=["GET"])
def home():
    return "✅ البوت شغال. Bot is running."


@app.route("/ping", methods=["GET"])
def ping():
    """
    كل زيارة هنا (من الكرون جوب) تخلي البوت صاحي + تفحص هل حان
    وقت مسح السوق أو دورة التعلم وتشغّلهم عند الحاجة
    Every visit here keeps the bot awake + checks whether it's
    time for a market scan or learning cycle and runs them if so
    """
    try:
        scheduler.on_ping()
    except Exception:
        log.exception("خطأ أثناء تنفيذ المهام المجدولة / error while running scheduled tasks")
    return jsonify({"status": "alive"})


@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    try:
        handlers.handle_update(update)
    except Exception:
        log.exception("خطأ أثناء معالجة تحديث تيلجرام / error while handling a Telegram update")
    return jsonify({"ok": True})


if __name__ == "__main__":
    # للتشغيل المحلي فقط للتجربة - على Render يشغّله gunicorn (شوف Procfile)
    # For local testing only - on Render, gunicorn runs it (see Procfile)
    if not TELEGRAM_BOT_TOKEN:
        log.warning("⚠️ TELEGRAM_BOT_TOKEN غير موجود بملف .env")
    app.run(host="0.0.0.0", port=5000, debug=True)
