import json

def _kb(rows):
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)

def main_menu(is_admin=False):
    rows = [
        [{"text": "📈 تحليل السوق", "callback_data": "menu_analyze"}],
        [{"text": "⭐ قائمة المراقبة", "callback_data": "menu_watchlist"}],
        [{"text": "📝 تسجيل صفقة", "callback_data": "menu_trade"}, {"text": "📂 صفقاتي", "callback_data": "menu_trades"}],
        [{"text": "📷 تحليل شارت بالـAI", "callback_data": "menu_ai_help"}],
        [{"text": "⚙️ الإعدادات", "callback_data": "menu_settings"}],
    ]
    if is_admin:
        rows.insert(0, [{"text": "👑 لوحة أحمد", "callback_data": "admin_panel"}])
    rows.append([{ "text": "ℹ️ مساعدة", "callback_data": "menu_help"}])
    return _kb(rows)

def admin_menu():
    return _kb([
        [{"text": "📊 حالة البوت", "callback_data": "admin_status"}, {"text": "🧠 التعلم", "callback_data": "admin_learning"}],
        [{"text": "👥 المستخدمون", "callback_data": "admin_users"}],
        [{"text": "📚 المعرفة", "callback_data": "admin_knowledge"}, {"text": "🧪 سجل النماذج", "callback_data": "admin_models"}],
        [{"text": "🛡️ دورة الإصدارات", "callback_data": "admin_models"}],
        [{"text": "➕ إضافة مستخدم", "callback_data": "admin_add_user"}],
        [{"text": "🔙 القائمة الرئيسية", "callback_data": "menu_main"}],
    ])

def market_type_menu(prefix):
    return _kb([
        [{"text": "🖥️ MT5", "callback_data": f"{prefix}_mt5"}],
        [{"text": "📊 سهم", "callback_data": f"{prefix}_stock"}, {"text": "💱 فوركس", "callback_data": f"{prefix}_forex"}],
        [{"text": "🪙 كريبتو", "callback_data": f"{prefix}_crypto"}],
        [{"text": "🔙 رجوع", "callback_data": "menu_main"}],
    ])

def watchlist_menu(items):
    rows = [[{"text": f"{it['symbol']} · {it['timeframe']}", "callback_data": f"quick_analyze_{it['market_type']}_{it['timeframe']}_{it['symbol']}"}] for it in items]
    rows.append([{"text": "🔙 رجوع", "callback_data": "menu_main"}])
    return _kb(rows)

def signal_feedback_kb(signal_id):
    return _kb([[{"text": "✅ صحيح", "callback_data": f"fb_correct_{signal_id}"}, {"text": "❌ خطأ", "callback_data": f"fb_incorrect_{signal_id}"}]])

def back_to_main():
    return _kb([[{"text": "🔙 القائمة الرئيسية", "callback_data": "menu_main"}]])

def trade_menu():
    return _kb([
        [{"text": "📂 الصفقات المفتوحة", "callback_data": "trade_open"}],
        [{"text": "📊 إحصائيات صفقاتي", "callback_data": "trade_stats"}],
        [{"text": "🔙 رجوع", "callback_data": "menu_main"}],
    ])
