"""Shadow/paper trading for candidate models. Never changes live recommendations."""
import json
from datetime import datetime, timezone
import database, data_fetcher, indicators
from validation import MIN_PAPER_SAMPLES

MOVE_PCT = 0.005
MAX_PAPER_HOURS = 24


def _score(strengths, weights):
    total = sum(weights.get(k, 0) for k in strengths) or 1.0
    return sum(strengths[k] * weights.get(k, 0) for k in strengths) / total


def _pnl(direction, entry, price):
    sign = 1 if direction == "BUY" else -1
    return (price - entry) / entry * 100 * sign


def run_once():
    candidate = database.get_latest_candidate(stage="PAPER")
    if not candidate:
        return {"status": "idle"}
    weights = json.loads(candidate["weights_json"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    closed = database.get_paper_trades(candidate["version"], "closed")
    open_trades = database.get_paper_trades(candidate["version"], "open")
    # First update existing paper positions.
    for trade in open_trades:
        price = data_fetcher.get_last_price(trade["symbol"], trade["market_type"], trade["timeframe"])
        if price is None:
            continue
        pnl = _pnl(trade["direction"], float(trade["entry_price"]), price)
        created = trade.get("created_at")
        age_hours = 0
        if created:
            try:
                age_hours = (now - created.replace(tzinfo=None)).total_seconds() / 3600
            except Exception:
                pass
        if abs(pnl) >= MOVE_PCT * 100 or age_hours >= MAX_PAPER_HOURS:
            outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
            database.close_paper_trade(trade["id"], price, pnl, outcome)

    # Then create at most one open shadow trade per watched symbol/timeframe.
    for item in database.get_all_watched_symbols():
        existing = [x for x in database.get_paper_trades(candidate["version"], "open") if x["symbol"] == item["symbol"].upper() and x["timeframe"] == item["timeframe"]]
        if existing:
            continue
        df = data_fetcher.fetch_ohlcv(item["symbol"], item["market_type"], days=30, timeframe=item["timeframe"])
        if df is None or len(df) < 60:
            continue
        strengths = indicators.compute_indicator_strengths(df)
        score = _score(strengths, weights)
        direction = "BUY" if score >= 0.60 else "SELL" if score <= 0.40 else "NEUTRAL"
        if direction == "NEUTRAL":
            continue
        price = float(df["close"].iloc[-1])
        database.create_paper_trade(candidate["version"], item["symbol"], item["market_type"], item["timeframe"], direction, price, {"score": score, "strengths": strengths})

    closed = database.get_paper_trades(candidate["version"], "closed")
    # Use the same strict quality gate as validation. Paper results are never sent as live alerts.
    if len(closed) >= MIN_PAPER_SAMPLES:
        from validation import paper_gate
        pnls = [float(x.get("pnl_pct") or 0) for x in closed]
        ok, summary = paper_gate(pnls, candidate.get("backtest_summary"))
        if ok:
            database.update_model_validation(candidate["version"], "APPROVAL", "awaiting_owner", True, paper_summary=json.dumps(summary, ensure_ascii=False))
            database.create_memory_snapshot("paper_pass", None)
            return {"status": "awaiting_owner", "version": candidate["version"], "summary": summary}
        if summary.get("status") == "rejected":
            database.update_model_validation(candidate["version"], "PAPER", "rejected", False, paper_summary=json.dumps(summary, ensure_ascii=False))
            database.create_memory_snapshot("paper_reject", None)
            return {"status": "rejected", "version": candidate["version"], "summary": summary}
    return {"status": "running", "version": candidate["version"], "closed": len(closed)}
