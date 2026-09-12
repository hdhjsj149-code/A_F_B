"""Local smoke tests. Run with: python test_v4_local.py"""
import os, tempfile

fd, path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["DATABASE_PATH"] = path
os.environ.pop("DATABASE_URL", None)

import database

database.init_db()
assert database.get_active_model_version()["version"] == 1
trade_id = database.record_trade(7601281598, "XAUUSD", "mt5", "15m", "BUY", 3500, 3480, 3540,
                                 reason="breakout", context={"exact": True},
                                 entry_time_utc="2026-09-12T14:30:00+00:00",
                                 entry_candle_ts="2026-09-12T14:30:00+00:00", data_source="MT5 read-only bridge")
trade = database.get_trade(trade_id, 7601281598)
assert trade["entry_candle_ts"] is not None
assert trade["data_source"] == "MT5 read-only bridge"
assert database.close_trade(trade_id, 7601281598, "WIN", 3530)
print("OK: database migration + trade context fields")
try:
    os.unlink(path)
except OSError:
    pass
