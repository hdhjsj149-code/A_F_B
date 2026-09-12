from datetime import datetime, timedelta
import database
import data_fetcher
import indicators
import learning
import telegram_api
import paper_engine
from config import SCAN_INTERVAL_MINUTES, LEARNING_CYCLE_HOURS, ALERT_SCORE_THRESHOLD


def on_ping():
    _maybe_run_market_scan()
    _maybe_run_learning_cycle()
    # Shadow-test candidates without ever feeding them to the live recommendation engine.
    try:
        paper_engine.run_once()
    except Exception:
        pass


def _due(key, interval):
    last = database.get_meta(key)
    if not last:
        return True
    try:
        return datetime.utcnow() - datetime.fromisoformat(last) >= interval
    except ValueError:
        return True


def _mark_done(key):
    database.set_meta(key, datetime.utcnow().isoformat())


def _maybe_run_market_scan():
    if not _due("last_scan_at", timedelta(minutes=SCAN_INTERVAL_MINUTES)):
        return
    _mark_done("last_scan_at")
    for item in database.get_all_watched_symbols():
        df = data_fetcher.fetch_ohlcv(item["symbol"], item["market_type"], timeframe=item["timeframe"])
        if df is None or len(df) < 60:
            continue
        score, strengths, direction, confidence = indicators.compute_composite_score(df)
        if score < ALERT_SCORE_THRESHOLD or direction == "NEUTRAL":
            continue
        price = float(df["close"].iloc[-1])
        text = indicators.format_analysis_text(item["symbol"], score, strengths, price, direction, confidence, item["timeframe"])
        for chat_id in database.get_watchers_of(item["symbol"], item["market_type"], item["timeframe"]):
            sent = telegram_api.send_message(chat_id, "🚨 *تنبيه من قائمة المراقبة*\n\n" + text)
            if sent.get("ok"):
                sid = database.save_signal(item["symbol"], item["market_type"], chat_id, sent["result"]["message_id"], price, score, strengths, item["timeframe"], direction, {"confidence": confidence, "data_source": df.attrs.get("source"), "provider": df.attrs.get("provider"), "source_symbol": df.attrs.get("source_symbol")})
                telegram_api.send_message(chat_id, "قيّم الإشارة لاحقاً للتعلم:", __import__('keyboards').signal_feedback_kb(sid))


def _maybe_run_learning_cycle():
    if not _due("last_learning_at", timedelta(hours=LEARNING_CYCLE_HOURS)):
        return
    _mark_done("last_learning_at")
    learning.run_learning_cycle()
