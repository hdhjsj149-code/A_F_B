"""Safe model validation pipeline.

A learned candidate can NEVER affect live recommendations directly. It must pass
backtesting, then paper trading, then explicit owner approval.
"""
import json
from datetime import datetime, timezone
import database

# Conservative defaults. These are deliberately configurable later.
MIN_BACKTEST_SAMPLES = 200
MIN_PAPER_SAMPLES = 50
MIN_BACKTEST_WIN_RATE = 0.52
MIN_PAPER_WIN_RATE = 0.50
MIN_PROFIT_FACTOR = 1.05
MAX_DRAWDOWN_PCT = 20.0
MAX_DEGRADATION_PCT = 5.0


def _metrics(results):
    if not results:
        return {"samples": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "profit_factor": 0.0, "max_drawdown_pct": 100.0}
    pnls = [float(x) for x in results]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    pf = sum(wins) / abs(sum(losses)) if losses else (999.0 if wins else 0.0)
    return {
        "samples": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(pnls) * 100,
        "profit_factor": pf,
        "max_drawdown_pct": max_dd,
    }


def build_candidate_from_results(version, candidate_weights, results, baseline_results=None):
    """Validate an already-computed candidate against historical/OOS results.

    The function is intentionally pure-ish: it only records validation metadata;
    it does not modify the live weights table.
    """
    metrics = _metrics(results)
    baseline = _metrics(baseline_results or [])
    if metrics["samples"] < MIN_BACKTEST_SAMPLES:
        return False, {"stage": "BACKTEST", "status": "rejected", "metrics": metrics, "baseline": baseline, "reason": "عدد عينات الـBacktest أقل من الحد الأدنى."}
    if metrics["win_rate"] < MIN_BACKTEST_WIN_RATE * 100:
        return False, {"stage": "BACKTEST", "status": "rejected", "metrics": metrics, "baseline": baseline, "reason": "Win rate أقل من الحد الأدنى."}
    if metrics["profit_factor"] < MIN_PROFIT_FACTOR:
        return False, {"stage": "BACKTEST", "status": "rejected", "metrics": metrics, "baseline": baseline, "reason": "Profit factor أقل من الحد الأدنى."}
    if metrics["max_drawdown_pct"] > MAX_DRAWDOWN_PCT:
        return False, {"stage": "BACKTEST", "status": "rejected", "metrics": metrics, "baseline": baseline, "reason": "Max drawdown أعلى من الحد المسموح."}
    if baseline["profit_factor"] > 0 and metrics["profit_factor"] < baseline["profit_factor"] * (1 - MAX_DEGRADATION_PCT / 100):
        return False, {"stage": "BACKTEST", "status": "rejected", "metrics": metrics, "baseline": baseline, "reason": "التطوير أسوأ من النموذج الحالي بأكثر من هامش التدهور المسموح."}
    return True, {"stage": "PAPER", "status": "paper", "metrics": metrics, "baseline": baseline, "candidate_weights": candidate_weights, "created_at": datetime.now(timezone.utc).isoformat()}


def paper_gate(paper_results, backtest_summary):
    metrics = _metrics(paper_results)
    if metrics["samples"] < MIN_PAPER_SAMPLES:
        return False, {"stage": "PAPER", "status": "rejected", "metrics": metrics, "reason": "Paper Trading لم يجمع عينات كافية."}
    if metrics["win_rate"] < MIN_PAPER_WIN_RATE * 100:
        return False, {"stage": "PAPER", "status": "rejected", "metrics": metrics, "reason": "Paper win rate أقل من الحد الأدنى."}
    if metrics["profit_factor"] < MIN_PROFIT_FACTOR:
        return False, {"stage": "PAPER", "status": "rejected", "metrics": metrics, "reason": "Paper profit factor أقل من الحد الأدنى."}
    if metrics["max_drawdown_pct"] > MAX_DRAWDOWN_PCT:
        return False, {"stage": "PAPER", "status": "rejected", "metrics": metrics, "reason": "Paper drawdown أعلى من الحد المسموح."}
    return True, {"stage": "APPROVAL", "status": "awaiting_owner", "metrics": metrics, "backtest": backtest_summary}


def approve(version, owner_id):
    from config import OWNER_USER_ID
    if int(owner_id) != int(OWNER_USER_ID):
        return False, "فقط مالك البوت يستطيع اعتماد نسخة."
    current = database.get_active_model_version()
    candidate = database.get_model_version(version)
    if not candidate:
        return False, "النسخة غير موجودة."
    if candidate.get("stage") != "APPROVAL" or candidate.get("status") != "awaiting_owner":
        return False, "النسخة لم تكمل Backtest وPaper Trading بنجاح."
    if current and int(candidate["version"]) <= int(current["version"]):
        return False, "لا يمكن اعتماد نسخة أقدم من النسخة الحالية."
    database.activate_model_version(version)
    database.create_memory_snapshot("model_approval", owner_id)
    database.add_audit(owner_id, "approve_model", {"version": version})
    return True, f"تم اعتماد v{version} كنسخة فعالة."


def rollback(version, owner_id):
    from config import OWNER_USER_ID
    if int(owner_id) != int(OWNER_USER_ID):
        return False, "فقط مالك البوت يستطيع التراجع."
    candidate = database.get_model_version(version)
    if not candidate or not candidate.get("validated_ok"):
        return False, "لا يمكن الرجوع إلى نسخة غير صالحة/غير مكتملة."
    database.activate_model_version(version)
    database.create_memory_snapshot("rollback", owner_id)
    database.add_audit(owner_id, "rollback_model", {"version": version})
    return True, f"تم الرجوع إلى v{version}."
