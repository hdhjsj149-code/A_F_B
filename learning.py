"""Continuous learning with a hard validation firewall.

Learning may create a candidate model, but it cannot change live weights.
Promotion path: candidate -> backtest -> paper -> owner approval -> active.
"""
import json
from datetime import datetime, timedelta
import database
import data_fetcher
from config import OUTCOME_HORIZON_DAYS, OWNER_USER_ID

MIN_SAMPLES = 30
LEARNING_RATE = 0.03
MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.40


def evaluate_pending_signals():
    cutoff = (datetime.utcnow() - timedelta(days=OUTCOME_HORIZON_DAYS)).isoformat()
    for sig in database.get_pending_signals_older_than(cutoff):
        price = data_fetcher.get_last_price(sig["symbol"], sig["market_type"], sig.get("timeframe", "1d"))
        entry = sig.get("price_at_signal")
        if price is None or not entry:
            continue
        change = (price - entry) / entry * 100
        direction = sig.get("direction", "NEUTRAL")
        outcome = change > 0.5 if direction == "BUY" else change < -0.5 if direction == "SELL" else abs(change) <= 0.5
        database.set_signal_outcome(sig["id"], "correct" if outcome else "incorrect", change)


def apply_feedback(signal_id, was_correct, user_id=None):
    sig = database.get_signal(signal_id)
    if not sig or (user_id is not None and sig.get("chat_id") != user_id):
        return False
    database.set_signal_outcome(signal_id, "correct" if was_correct else "incorrect")
    return True


def _candidate_weights(labeled):
    current = database.get_weights()
    names = list(current.keys())
    good, bad = {n: [] for n in names}, {n: [] for n in names}
    for sig in labeled:
        try:
            strengths = json.loads(sig.get("indicators_json") or "{}")
        except json.JSONDecodeError:
            continue
        bucket = good if sig["status"] == "correct" else bad
        for n in names:
            if n in strengths:
                bucket[n].append(float(strengths[n]))
    candidate = dict(current)
    for n in names:
        if not good[n] and not bad[n]:
            continue
        gc = sum(good[n]) / len(good[n]) if good[n] else 0.5
        bc = sum(bad[n]) / len(bad[n]) if bad[n] else 0.5
        candidate[n] = max(MIN_WEIGHT, min(MAX_WEIGHT, current[n] + LEARNING_RATE * (gc - bc)))
    total = sum(candidate.values()) or 1
    return {k: round(v / total, 5) for k, v in candidate.items()}


def run_learning_cycle():
    evaluate_pending_signals()
    labeled = database.get_labeled_signals()
    closed_trades = database.get_closed_trades(OWNER_USER_ID)
    total_samples = len(labeled) + len(closed_trades)
    active = database.get_active_model_version()
    active_version = active["version"] if active else 1

    if total_samples < MIN_SAMPLES:
        database.add_learning_run(total_samples, active_version, active_version, False, f"تأجيل: نحتاج {MIN_SAMPLES} نتيجة، والمتوفر {total_samples}. لم يتم تغيير النموذج الفعال.")
        return {"changed": False, "samples": total_samples, "stage": "COLLECTING"}

    trade_samples = []
    for trade in closed_trades:
        try:
            context = json.loads(trade.get("market_context_json") or "{}")
            strengths = context.get("strengths") or {}
            pnl = float(trade.get("pnl_pct") or 0)
            trade_samples.append({"status": "correct" if pnl > 0 else "incorrect", "indicators_json": json.dumps(strengths)})
        except (ValueError, TypeError, json.JSONDecodeError):
            continue

    current = database.get_weights()
    candidate = _candidate_weights(labeled + trade_samples)
    safe = all(abs(candidate[k] - current[k]) <= max(0.015, current[k] * 0.15) for k in candidate)
    if not safe or all(abs(candidate[k] - current[k]) < 0.002 for k in candidate):
        database.add_learning_run(total_samples, active_version, active_version, False, "لا يوجد تغيير آمن وكافٍ. النموذج الفعال لم يتغير.")
        return {"changed": False, "samples": total_samples, "stage": "NO_CHANGE"}

    candidate_version = database.create_candidate_model(candidate, reason="continuous_learning", parent_version=active_version)
    database.add_learning_run(total_samples, active_version, candidate_version, False, f"تم إنشاء مرشح v{candidate_version}. ممنوع أن يؤثر على التوصيات قبل Backtest ثم Paper ثم اعتماد أحمد.")
    database.create_memory_snapshot("learning_candidate", OWNER_USER_ID)
    return {"changed": False, "candidate_version": candidate_version, "samples": total_samples, "stage": "BACKTEST"}
