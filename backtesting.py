"""Deterministic, no-lookahead backtesting for candidate model versions.

This is a safety gate, not a promise of future performance. It uses only
historical OHLCV and never writes candidate weights into the live weights table.
"""
import json
import numpy as np
import indicators
import database
import data_fetcher
from validation import MIN_BACKTEST_SAMPLES, MIN_BACKTEST_WIN_RATE, MIN_PROFIT_FACTOR, MAX_DRAWDOWN_PCT, MAX_DEGRADATION_PCT

HORIZON_BARS = 5
MOVE_PCT = 0.005


def _score(strengths, weights):
    total = sum(weights.get(k, 0) for k in strengths) or 1.0
    score = sum(strengths[k] * weights.get(k, 0) for k in strengths) / total
    return score


def _run(df, weights):
    pnls = []
    for i in range(60, len(df) - HORIZON_BARS):
        window = df.iloc[: i + 1]
        strengths = indicators.compute_indicator_strengths(window)
        score = _score(strengths, weights)
        direction = "BUY" if score >= 0.60 else "SELL" if score <= 0.40 else "NEUTRAL"
        if direction == "NEUTRAL":
            continue
        entry = float(df["close"].iloc[i])
        future = df.iloc[i + 1:i + 1 + HORIZON_BARS]
        if direction == "BUY":
            hit_tp = (future["high"].astype(float) >= entry * (1 + MOVE_PCT)).any()
            hit_sl = (future["low"].astype(float) <= entry * (1 - MOVE_PCT)).any()
        else:
            hit_tp = (future["low"].astype(float) <= entry * (1 - MOVE_PCT)).any()
            hit_sl = (future["high"].astype(float) >= entry * (1 + MOVE_PCT)).any()
        # Conservative tie-break: if both occur in the same horizon, count as loss
        # because candle ordering inside OHLC is unknown.
        if hit_tp and not hit_sl:
            pnls.append(MOVE_PCT * 100)
        elif hit_sl:
            pnls.append(-MOVE_PCT * 100)
    return pnls


def run_candidate(version):
    model = database.get_model_version(version)
    if not model:
        return False, "النسخة غير موجودة."
    if model.get("stage") != "BACKTEST":
        return False, "النسخة ليست في مرحلة Backtest."
    weights = json.loads(model["weights_json"])
    active = database.get_active_model_version()
    baseline_weights = json.loads(active["weights_json"]) if active else database.get_weights()
    candidate_results, baseline_results = [], []
    items = database.get_all_watched_symbols()
    if not items:
        return False, "أضف رموزاً إلى قائمة المراقبة أولاً لتوفير بيانات للاختبار."
    for item in items:
        df = data_fetcher.fetch_ohlcv(item["symbol"], item["market_type"], days=180, timeframe=item["timeframe"])
        if df is None or len(df) < 80:
            continue
        split = int(len(df) * 0.70)
        # Train/selection area is ignored here; gate uses the final 30% OOS portion.
        oos = df.iloc[split:].copy()
        candidate_results.extend(_run(oos, weights))
        baseline_results.extend(_run(oos, baseline_weights))
    from validation import build_candidate_from_results
    ok, summary = build_candidate_from_results(version, weights, candidate_results, baseline_results)
    database.update_model_validation(version, "PAPER" if ok else "BACKTEST", "paper" if ok else "rejected", ok, json.dumps(summary, ensure_ascii=False))
    database.create_memory_snapshot("backtest_pass" if ok else "backtest_reject", None)
    return ok, summary
