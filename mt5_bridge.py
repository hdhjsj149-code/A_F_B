"""Minimal read-only HTTP bridge for MetaTrader 5.

Run this on Windows/VPS where the MT5 terminal is installed and logged in.
It exposes ONLY health, tick, symbol and OHLCV-read endpoints.
There is intentionally no order/trade endpoint in this file.
"""
import os
from functools import wraps

from flask import Flask, jsonify, request

try:
    import MetaTrader5 as mt5
except ImportError as exc:
    raise SystemExit("Install MetaTrader5 on the MT5 machine: pip install MetaTrader5") from exc

app = Flask(__name__)
TOKEN = os.getenv("MT5_BRIDGE_TOKEN", "").strip()
HOST = os.getenv("MT5_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("MT5_BRIDGE_PORT", "8765"))

TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
      "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
      "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1}


def auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not TOKEN:
            return jsonify(ok=False, error="MT5_BRIDGE_TOKEN is not configured"), 503
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return jsonify(ok=False, error="unauthorized"), 401
        return fn(*args, **kwargs)
    return wrapper


def _ensure():
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def _symbol(symbol):
    name = str(symbol).upper().strip()
    _ensure()
    info = mt5.symbol_info(name)
    if info is None:
        raise ValueError(f"Symbol not found in MT5: {name}")
    if not info.visible and not mt5.symbol_select(name, True):
        raise ValueError(f"Could not select symbol in MT5: {name}")
    return name


def _rates_to_json(rates):
    rows = []
    for r in rates:
        rows.append({
            "time": int(r["time"]),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
            "spread": int(r["spread"]), "real_volume": int(r["real_volume"]),
        })
    return rows


@app.get("/health")
@auth
def health():
    try:
        _ensure()
        term = mt5.terminal_info()
        return jsonify(ok=True, connected=True, trade_allowed=False,
                       terminal_connected=bool(term), mode="READ_ONLY")
    except Exception as exc:
        return jsonify(ok=False, connected=False, trade_allowed=False, error=str(exc)), 503


@app.get("/tick")
@auth
def tick():
    try:
        symbol = _symbol(request.args.get("symbol", ""))
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            raise ValueError(f"No tick for {symbol}")
        return jsonify(ok=True, symbol=symbol, tick={"time": int(t.time), "bid": float(t.bid), "ask": float(t.ask), "last": float(t.last)})
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 400


@app.get("/rates")
@auth
def rates():
    try:
        symbol = _symbol(request.args.get("symbol", ""))
        tf_name = request.args.get("timeframe", "M15").upper()
        tf = TF.get(tf_name)
        if tf is None:
            raise ValueError(f"Unsupported timeframe: {tf_name}")
        count = max(1, min(int(request.args.get("count", "500")), 2000))
        end_raw = request.args.get("end_time")
        if end_raw:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            rates = mt5.copy_rates_from(symbol, tf, dt, count)
        else:
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None:
            raise RuntimeError(f"copy_rates failed: {mt5.last_error()}")
        return jsonify(ok=True, symbol=symbol, timeframe=tf_name, rates=_rates_to_json(rates))
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 400


if __name__ == "__main__":
    # Keep the bridge local by default. For a remote Render bot, put it behind
    # HTTPS/reverse proxy/VPN and set a long random bearer token.
    app.run(host=HOST, port=PORT, debug=False)
