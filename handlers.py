"""Telegram interaction layer and Ahmed admin panel."""
import json
import database
import data_fetcher
import indicators
import learning
import backtesting
import validation
import market_context
from datetime import datetime, timezone
import keyboards
import telegram_api
from gemini_vision import analyze_chart_image
from config import OWNER_USER_ID, ALLOWED_USER_IDS

USER_STATE = {}

def _is_allowed(user_id):
    return database.is_active_user(user_id) or user_id == OWNER_USER_ID or user_id in ALLOWED_USER_IDS

def _is_admin(user_id):
    return database.is_admin(user_id)

def handle_update(update):
    if "callback_query" in update:
        _handle_callback(update["callback_query"])
    elif "message" in update:
        _handle_message(update["message"])

def _handle_message(msg):
    user = msg.get("from", {})
    user_id = user["id"]
    chat_id = msg["chat"]["id"]
    database.upsert_user(user_id, user.get("username"))
    if not _is_allowed(user_id):
        telegram_api.send_message(chat_id, "🚫 البوت خاص حالياً. أحمد لم يفعّل حسابك بعد.")
        return
    if "photo" in msg:
        _handle_photo(msg, chat_id, user_id)
        return
    text = msg.get("text", "").strip()
    if text == "/start":
        telegram_api.send_message(chat_id, "👋 أهلاً بك. ده *مستشار السوق* الخاص بأحمد.\n\nاختار من اللوحة:", keyboards.main_menu(_is_admin(user_id)))
        return
    if text == "/help":
        _send_help(chat_id)
        return
    if text.startswith("/mt5status") and _is_admin(user_id):
        try:
            import mt5_connector
            h = mt5_connector.health()
            status = "🟢 متصل" if h.get("connected") else "🔴 غير متصل"
            telegram_api.send_message(chat_id, f"🖥️ *MT5 Read-Only*\n\nالحالة: {status}\nالوضع: `{h.get('mode', 'READ_ONLY')}`\nالتداول من البوت: ❌ ممنوع", keyboards.admin_menu())
        except Exception as exc:
            telegram_api.send_message(chat_id, f"🔴 MT5 غير متاح.\n`{str(exc)[:500]}`\n\nتأكد أن MT5 والـbridge شغالان.", keyboards.admin_menu())
        return
    if text.startswith("/backtest") and _is_admin(user_id):
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            telegram_api.send_message(chat_id, "الاستخدام: `/backtest VERSION`", keyboards.admin_menu())
            return
        ok, result = backtesting.run_candidate(int(parts[1]))
        if ok:
            telegram_api.send_message(chat_id, f"🟢 Backtest ناجح للنسخة v{parts[1]}. انتقلت إلى PAPER. لا تأثير على التوصيات الفعلية حتى الآن.", keyboards.admin_menu())
        else:
            msg = result if isinstance(result, str) else result.get("reason", "تم رفض النسخة")
            telegram_api.send_message(chat_id, f"🔴 Backtest مرفوض: {msg}", keyboards.admin_menu())
        return
    if text.startswith("/approve") and _is_admin(user_id):
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            telegram_api.send_message(chat_id, "الاستخدام: `/approve VERSION` بعد نجاح Backtest وPaper.", keyboards.admin_menu())
            return
        ok, msg = validation.approve(int(parts[1]), user_id)
        telegram_api.send_message(chat_id, ("🟢 " if ok else "🔴 ") + msg, keyboards.admin_menu())
        return
    if text.startswith("/rollback") and _is_admin(user_id):
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            telegram_api.send_message(chat_id, "الاستخدام: `/rollback VERSION`", keyboards.admin_menu())
            return
        ok, msg = validation.rollback(int(parts[1]), user_id)
        telegram_api.send_message(chat_id, ("🔄 " if ok else "🔴 ") + msg, keyboards.admin_menu())
        return
    if text.startswith("/addnote") and _is_admin(user_id):
        note = text.replace("/addnote", "", 1).strip()
        if note:
            database.add_expert_note(user_id, note)
            database.add_audit(user_id, "add_expert_note")
            telegram_api.send_message(chat_id, "✅ أضفت المعلومة إلى ذاكرة المعرفة.")
        return
    if text.startswith("/teach") and _is_admin(user_id):
        payload = text.replace("/teach", "", 1).strip()
        if "|" not in payload:
            telegram_api.send_message(chat_id, "الاستخدام: `/teach عنوان | المعلومة`", keyboards.admin_menu())
        else:
            title, content = [x.strip() for x in payload.split("|", 1)]
            if title and content:
                database.add_knowledge(user_id, title, content, "manual", 0.7, "Ahmed")
                database.add_audit(user_id, "add_knowledge", {"title": title})
                telegram_api.send_message(chat_id, "🧠✅ حفظت المعلومة في قاعدة المعرفة.", keyboards.admin_menu())
        return
    if text.startswith("/adduser") and _is_admin(user_id):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            database.set_user_active(int(parts[1]), True)
            database.add_audit(user_id, "activate_user", {"target": int(parts[1])})
            telegram_api.send_message(chat_id, f"✅ تم تفعيل المستخدم `{parts[1]}`.")
        else:
            telegram_api.send_message(chat_id, "الاستخدام: `/adduser 123456789`")
        return
    if text.startswith("/trade"):
        _handle_trade_command(text, user_id, chat_id)
        return
    if text.startswith("/close"):
        _handle_close_command(text, user_id, chat_id)
        return
    state = USER_STATE.get(user_id)
    if state and text:
        _consume_state(user_id, chat_id, text, state)
        return
    telegram_api.send_message(chat_id, "استخدم /start لفتح لوحة التحكم.", keyboards.main_menu(_is_admin(user_id)))

def _handle_photo(msg, chat_id, user_id):
    telegram_api.send_message(chat_id, "🔎 جاري تحليل الشارت بالـAI...")
    largest = msg["photo"][-1]
    path = telegram_api.get_file_path(largest["file_id"])
    image = telegram_api.download_file(path) if path else None
    if not image:
        telegram_api.send_message(chat_id, "⚠️ تعذر تحميل الصورة.")
        return
    result = analyze_chart_image(image, msg.get("caption", ""))
    database.add_audit(user_id, "ai_chart_analysis")
    telegram_api.send_message(chat_id, result, parse_mode="Markdown")

def _consume_state(user_id, chat_id, text, state):
    action = state.get("action")
    if action == "analyze":
        _run_and_send_analysis(chat_id, text.upper(), state["market_type"], user_id, state.get("timeframe", "1d"))
    elif action == "add":
        ok = database.add_to_watchlist(user_id, text.upper(), state["market_type"], state.get("timeframe", "1d"))
        telegram_api.send_message(chat_id, "✅ تمت الإضافة." if ok else "ℹ️ موجودة بالفعل.", keyboards.back_to_main())
    elif action == "trade":
        _handle_trade_command(text, user_id, chat_id)
    elif action == "add_user":
        if text.isdigit() and int(text) > 0 and _is_admin(user_id):
            target = int(text)
            database.set_user_active(target, True)
            database.add_audit(user_id, "activate_user", {"target": target})
            telegram_api.send_message(chat_id, f"✅ تم تفعيل المستخدم `{target}`.", keyboards.admin_menu())
        else:
            telegram_api.send_message(chat_id, "⚠️ أرسل Telegram User ID صحيح.", keyboards.admin_menu())
    USER_STATE.pop(user_id, None)

def _run_and_send_analysis(chat_id, symbol, market_type, user_id=None, timeframe="1d"):
    df = data_fetcher.fetch_ohlcv(symbol, market_type, timeframe=timeframe)
    if df is None or len(df) < 60:
        telegram_api.send_message(chat_id, f"⚠️ البيانات غير كافية لـ {symbol} على {timeframe}.", keyboards.back_to_main())
        return
    score, strengths, direction, confidence = indicators.compute_composite_score(df)
    price = float(df["close"].iloc[-1])
    text = indicators.format_analysis_text(symbol, score, strengths, price, direction, confidence, timeframe)
    sent = telegram_api.send_message(chat_id, text, keyboards.back_to_main())
    if sent.get("ok") and score >= 60 and direction != "NEUTRAL":
        sid = database.save_signal(symbol, market_type, chat_id, sent["result"]["message_id"], price, score, strengths, timeframe, direction, {"confidence": confidence, "data_source": df.attrs.get("source"), "provider": df.attrs.get("provider"), "source_symbol": df.attrs.get("source_symbol")})
        telegram_api.send_message(chat_id, "📌 سجّلت الإشارة للتعلم. قيّمها لاحقاً:", keyboards.signal_feedback_kb(sid))

def _handle_trade_command(text, user_id, chat_id):
    # /trade XAUUSD mt5 15m BUY 3500 3480 3540 2026-09-12T14:30:00 breakout
    # Timestamp is optional; if omitted, current UTC time is used and clearly marked.
    p = text.split(maxsplit=8)
    if len(p) < 8:
        telegram_api.send_message(chat_id, "الصيغة:\n`/trade SYMBOL mt5 TIMEFRAME BUY|SELL ENTRY SL TP [UTC_TIME] [سبب]`\nمثال:\n`/trade XAUUSD mt5 15m BUY 3500 3480 3540 2026-09-12T14:30:00 breakout`\n\nاستخدم UTC بصيغة ISO. لو ما كتبت الزمن، يستخدم البوت لحظة التسجيل الحالية.", keyboards.trade_menu())
        return
    try:
        _, symbol, market_type, timeframe, direction, entry, sl, tp, *rest = p
        symbol = symbol.upper().strip()
        market_type = market_type.lower().strip()
        timeframe = timeframe.lower().strip()
        direction = direction.upper().strip()
        if market_type not in {"mt5", "crypto", "stock", "forex"}:
            raise ValueError("نوع سوق غير مدعوم")
        if timeframe not in {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}:
            raise ValueError("فريم غير مدعوم")
        if direction not in {"BUY", "SELL"}:
            raise ValueError("الاتجاه يجب BUY أو SELL")
        entry_f, sl_f, tp_f = float(entry), float(sl), float(tp)
        if min(entry_f, sl_f, tp_f) <= 0:
            raise ValueError("الأسعار يجب أن تكون موجبة")
        if direction == "BUY" and not (sl_f < entry_f < tp_f):
            raise ValueError("في BUY يجب أن يكون SL < Entry < TP")
        if direction == "SELL" and not (tp_f < entry_f < sl_f):
            raise ValueError("في SELL يجب أن يكون TP < Entry < SL")

        payload = rest[0].strip() if rest else ""
        entry_time = datetime.now(timezone.utc)
        supplied_time = False
        reason = payload
        if payload:
            first, *remaining = payload.split(maxsplit=1)
            if first.upper() == "NOW":
                reason = remaining[0] if remaining else ""
                supplied_time = True
            else:
                try:
                    parsed = market_context.parse_utc(first)
                    entry_time = parsed
                    supplied_time = True
                    reason = remaining[0] if remaining else ""
                except (ValueError, TypeError):
                    pass

        context = market_context.resolve_trade_context(symbol, market_type, timeframe, entry_time, entry_f)
        context["entry_time_supplied"] = supplied_time
        if not supplied_time:
            context["warnings"] = context.get("warnings", []) + ["لم يُحدد وقت تاريخي؛ تم ربط الصفقة بوقت تسجيلها الحالي UTC."]

        trade_id = database.record_trade(
            user_id, symbol, market_type, timeframe, direction, entry_f, sl_f, tp_f,
            reason, context=context, entry_time_utc=entry_time.isoformat(),
            entry_candle_ts=context.get("entry_candle_ts"), data_source=context.get("source")
        )
        database.add_audit(user_id, "record_trade", {"trade_id": trade_id, "source": market_type, "entry_time_utc": entry_time.isoformat()})

        lines = [f"✅ تم تسجيل الصفقة #{trade_id}."]
        if context.get("entry_candle_ts"):
            exact = "🟢 مطابقة" if context.get("exact") else "🟡 غير مطابقة تماماً"
            lines.append(f"شمعة الدخول: `{context['entry_candle_ts']}` UTC — {exact}")
            candle = context.get("entry_candle_ohlcv", {})
            if candle:
                lines.append(f"OHLC: `{candle.get('open')}` / `{candle.get('high')}` / `{candle.get('low')}` / `{candle.get('close')}`")
            c = context.get("context") or {}
            if c:
                lines.append(f"المحرك وقت الدخول: *{c.get('direction','NEUTRAL')}* — ثقة {c.get('confidence',0):.1f}%")
                pats = c.get("candlestick_patterns") or []
                if pats:
                    lines.append("الشموع: " + ", ".join(pats))
            warnings = context.get("warnings") or []
            if warnings:
                lines.append("⚠️ " + "\n⚠️ ".join(warnings[:3]))
        else:
            lines.append("⚠️ لم أستطع ربط الصفقة بشمعة MT5؛ الصفقة محفوظة لكن لا تعتبر عينة سياق دقيقة للتعلم.")
        lines.append("\nالصفقة استشارية فقط، والبوت لا يملك أي مسار لتنفيذ أو تعديل أو إغلاق أو سحب من حساب التداول.")
        telegram_api.send_message(chat_id, "\n".join(lines), keyboards.trade_menu())
    except Exception as exc:
        telegram_api.send_message(chat_id, f"⚠️ لم يتم تسجيل الصفقة. {str(exc)[:500]}", keyboards.trade_menu())

def _handle_close_command(text, user_id, chat_id):
    # /close TRADE_ID EXIT_PRICE [notes]
    p = text.split(maxsplit=3)
    if len(p) < 3 or not p[1].isdigit():
        telegram_api.send_message(chat_id, "الصيغة: `/close TRADE_ID EXIT_PRICE [ملاحظة]`", keyboards.trade_menu())
        return
    try:
        trade_id = int(p[1]); exit_price = float(p[2]); notes = p[3] if len(p) > 3 else None
        trade = database.get_trade(trade_id, user_id)
        if not trade:
            telegram_api.send_message(chat_id, "⚠️ الصفقة غير موجودة أو ليست لك.")
            return
        sign = 1 if trade["direction"] == "BUY" else -1
        pnl = ((exit_price - trade["entry_price"]) / trade["entry_price"]) * 100 * sign
        outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
        ok = database.close_trade(trade_id, user_id, outcome, exit_price, pnl, notes)
        if ok:
            database.add_audit(user_id, "close_trade", {"trade_id": trade_id, "outcome": outcome})
            telegram_api.send_message(chat_id, f"✅ أغلقت الصفقة #{trade_id}.\nالنتيجة: *{outcome}*\nP/L: *{pnl:.2f}%*\nسيتم إدخالها في التعلم مع بقية العينات.", keyboards.trade_menu())
    except Exception:
        telegram_api.send_message(chat_id, "⚠️ بيانات الإغلاق غير صحيحة.")


def _send_help(chat_id):
    telegram_api.send_message(chat_id, "📖 *الاستخدام*\n\n• تحليل السوق: Python/TA بدون AI.\n• MT5: قراءة الأسعار والشموع فقط عبر Read-Only Bridge.\n• `/mt5status`: حالة اتصال MT5 (للإدارة).\n• أرسل صورة شارت: AI Vision فقط.\n• `/trade ...`: يسجل الصفقة ويربطها بوقت/شمعة MT5 إذا توفر الاتصال.\n• استخدم وقت الدخول UTC بصيغة ISO للصفقات التاريخية.\n• التعلّم يجمع نتائج كثيرة ولا يغيّر النموذج من صفقة واحدة.\n• الذاكرة الدائمة في PostgreSQL على Render.\n\n⚠️ البوت استشاري وليس ضماناً للربح.", keyboards.back_to_main())

def _handle_callback(cq):
    user_id = cq["from"]["id"]
    chat_id = cq["message"]["chat"]["id"]
    message_id = cq["message"]["message_id"]
    data = cq["data"]
    database.upsert_user(user_id, cq["from"].get("username"))
    telegram_api.answer_callback_query(cq["id"])
    if not _is_allowed(user_id):
        telegram_api.send_message(chat_id, "🚫 غير مصرح لك.")
        return
    if data == "menu_main":
        telegram_api.edit_message(chat_id, message_id, "اختر من القائمة:", keyboards.main_menu(_is_admin(user_id)))
    elif data == "admin_panel" and _is_admin(user_id):
        telegram_api.edit_message(chat_id, message_id, "👑 *لوحة أحمد*\n\nإدارة البوت والذاكرة والتعلم والمستخدمين:", keyboards.admin_menu())
    elif data == "admin_status" and _is_admin(user_id):
        s = database.get_learning_stats()
        telegram_api.edit_message(chat_id, message_id, f"📊 *حالة البوت*\n\nالصفقات: {s['trades']}\nالصفقات المغلقة: {s['closed_trades']}\nالإشارات: {s['signals']}\nالإشارات المقيمة: {s['labeled_signals']}\nالمعرفة: {s['knowledge']}\nإصدار النموذج: v{s['model_version']}", keyboards.admin_menu())
    elif data == "admin_learning" and _is_admin(user_id):
        s = database.get_learning_stats(); w = database.get_weights()
        wt = "\n".join(f"• {k}: {v:.3f}" for k,v in w.items())
        telegram_api.edit_message(chat_id, message_id, f"🧠 *التعلم المستمر*\n\nعينة الإشارات المقيمة: {s['labeled_signals']}\nإصدار: v{s['model_version']}\n\nالأوزان:\n{wt}\n\nالتحديث المحافظ يحتاج عينة كافية ويُسجل كنسخة جديدة.", keyboards.admin_menu())
    elif data == "admin_users" and _is_admin(user_id):
        users = database.list_users()
        txt = "👥 *المستخدمون*\n\n" + "\n".join(f"{u['user_id']} — {'🟢' if u['active'] else '🔴'} — {u['role']}" for u in users[:30])
        telegram_api.edit_message(chat_id, message_id, txt, keyboards.admin_menu())
    elif data == "admin_models" and _is_admin(user_id):
        models = database.get_model_history(10)
        txt = "🧪 *سجل النماذج*\n\n" + "\n".join(f"v{m['version']} — {m.get('stage','?')} — {m.get('status','?')} — {m['reason']}" for m in models)
        telegram_api.edit_message(chat_id, message_id, txt, keyboards.admin_menu())
    elif data == "admin_add_user" and _is_admin(user_id):
        USER_STATE[user_id] = {"action": "add_user"}
        telegram_api.edit_message(chat_id, message_id, "أرسل Telegram User ID للمستخدم الذي تريد تفعيله.", keyboards.back_to_main())
    elif data == "admin_knowledge" and _is_admin(user_id):
        k = database.get_knowledge(15)
        txt = "📚 *المعرفة المحفوظة*\n\n" + ("\n".join(f"• {x['title']} ({x['category']})" for x in k) or "لا توجد عناصر بعد.")
        telegram_api.edit_message(chat_id, message_id, txt, keyboards.admin_menu())
    elif data == "menu_analyze":
        telegram_api.edit_message(chat_id, message_id, "اختر نوع السوق:", keyboards.market_type_menu("analyze"))
    elif data == "menu_watchlist":
        items = database.get_user_watchlist(user_id)
        telegram_api.edit_message(chat_id, message_id, "⭐ قائمة المراقبة:" if items else "القائمة فاضية.", keyboards.watchlist_menu(items) if items else keyboards.back_to_main())
    elif data == "menu_trade":
        telegram_api.edit_message(chat_id, message_id, "📝 تسجيل الصفقة:\n`/trade SYMBOL mt5 TIMEFRAME BUY|SELL ENTRY SL TP [UTC_TIME] [سبب]`\n\nمثال:\n`/trade XAUUSD mt5 15m BUY 3500 3480 3540 2026-09-12T14:30:00 breakout`\n\nالبوت يقرأ MT5 فقط ولا ينفذ أي صفقة.", keyboards.trade_menu())
    elif data == "menu_trades":
        rows = database.get_open_trades(user_id)
        txt = "📂 *صفقاتك المفتوحة*\n\n" + ("\n".join(f"#{r['id']} {r['symbol']} {r['direction']} Entry {r['entry_price']} SL {r['stop_loss']} TP {r['take_profit']}" for r in rows) or "ما عندك صفقات مفتوحة.")
        telegram_api.edit_message(chat_id, message_id, txt, keyboards.trade_menu())
    elif data == "trade_open":
        rows = database.get_open_trades(user_id)
        txt = "📂 *الصفقات المفتوحة*\n\n" + ("\n".join(f"#{r['id']} {r['symbol']} {r['direction']} {r['entry_price']}" for r in rows) or "لا توجد صفقات مفتوحة.")
        telegram_api.edit_message(chat_id, message_id, txt, keyboards.trade_menu())
    elif data == "trade_stats":
        s = database.get_trade_stats(user_id)
        total = s.get("total") or 0; wins = s.get("wins") or 0
        wr = wins / max(1, (wins + (s.get("losses") or 0))) * 100
        telegram_api.edit_message(chat_id, message_id, f"📊 *إحصائيات صفقاتك*\n\nالإجمالي: {total}\nالرابحة: {wins}\nالخاسرة: {s.get('losses') or 0}\nWin rate: {wr:.1f}%\nمتوسط P/L: {s.get('avg_pnl') or 0:.2f}%", keyboards.trade_menu())
    elif data == "menu_settings":
        w = database.get_weights(); txt = "⚙️ *الأوزان الحالية*\n\n" + "\n".join(f"• {k}: {v:.3f}" for k,v in w.items())
        telegram_api.edit_message(chat_id, message_id, txt, keyboards.back_to_main())
    elif data == "menu_help":
        _send_help(chat_id)
    elif data == "menu_ai_help":
        telegram_api.edit_message(chat_id, message_id, "📷 أرسل صورة الشارت في المحادثة.\n\nالـAI هنا مخصص للرؤية وتحليل الصورة فقط. باقي التحليل الحسابي لا يعتمد على AI.", keyboards.back_to_main())
    elif data.startswith("analyze_"):
        market_type = data.split("_",1)[1]
        USER_STATE[user_id] = {"action": "analyze", "market_type": market_type, "timeframe": "1d"}
        telegram_api.edit_message(chat_id, message_id, f"أرسل رمز {market_type} للتحليل (حالياً الفريم الافتراضي 1d).", keyboards.back_to_main())
    elif data.startswith("quick_analyze_"):
        _, _, market_type, timeframe, symbol = data.split("_", 4)
        _run_and_send_analysis(chat_id, symbol, market_type, user_id, timeframe)
    elif data.startswith("fb_correct_") or data.startswith("fb_incorrect_"):
        signal_id = int(data.rsplit("_",1)[1])
        ok = learning.apply_feedback(signal_id, data.startswith("fb_correct_"), user_id)
        telegram_api.answer_callback_query(cq["id"], "تم حفظ التقييم." if ok else "الإشارة غير متاحة لك.", show_alert=True)
    elif data == "menu_add":
        telegram_api.edit_message(chat_id, message_id, "اختر السوق:", keyboards.market_type_menu("add"))
    elif data.startswith("add_"):
        market_type = data.split("_",1)[1]
        USER_STATE[user_id] = {"action": "add", "market_type": market_type, "timeframe": "1d"}
        telegram_api.edit_message(chat_id, message_id, f"أرسل رمز {market_type} لإضافته.", keyboards.back_to_main())
