"""Read-only MT5 market-data connector.

The production bot talks to a tiny read-only bridge running on the machine/VPS
where the MetaTrader 5 terminal is installed. No trading endpoint is exposed
or called. The bridge returns only ticks and OHLCV bars.
"""
import os
from datetime import datetime, timezone

import pandas as pd
import requests

MT5_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "").strip().rstrip("/")
MT5_BRIDGE_TOKEN = os.getenv("MT5_BRIDGE_TOKEN", "").strip()
MT5_TIMEOUT_SECONDS = float(os.getenv("MT5_TIMEOUT_SECONDS", "10"))

TIMEFRAME_MAP = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D1", "1w": "W1",
}


def configured():
    return bool(MT5_BRIDGE_URL and MT5_BRIDGE_TOKEN)


def _headers():
    return {"Authorization": f"Bearer {MT5_BRIDGE_TOKEN}"}


def _get(path, params=None):
    if not configured():
        raise RuntimeError("MT5_BRIDGE_URL/MT5_BRIDGE_TOKEN غير مضبوطين")
    r = requests.get(f"{MT5_BRIDGE_URL}{path}", params=params or {}, headers=_headers(), timeout=MT5_TIMEOUT_SECONDS)
    r.raise_for_status()
    payload = r.json()
    if payload.get("ok") is False:
        raise RuntimeError(payload.get("error", "MT5 bridge error"))
    return payload


def health():
    return _get("/health")


def get_tick(symbol):
    return _get("/tick", {"symbol": symbol.upper()})


def fetch_ohlcv(symbol, timeframe="15m", count=500, end_time=None):
    tf = TIMEFRAME_MAP.get(timeframe)
    if not tf:
        raise ValueError(f"Unsupported MT5 timeframe: {timeframe}")
    params = {"symbol": symbol.upper(), "timeframe": tf, "count": max(1, min(int(count), 2000))}
    if end_time:
        if isinstance(end_time, datetime):
            dt = end_time
        else:
            dt = datetime.fromisoformat(str(end_time).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        params["end_time"] = dt.astimezone(timezone.utc).isoformat()
    payload = _get("/rates", params)
    rows = payload.get("rates", [])
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if "time" not in df.columns:
        return None
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time"]).set_index("time").sort_index()
    required = ["open", "high", "low", "close"]
    for col in required:
        if col not in df.columns:
            return None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = pd.to_numeric(df.get("tick_volume", 0), errors="coerce").fillna(0)
    return df.dropna(subset=required)


def resolve_candle(symbol, timeframe, entry_time, tolerance_minutes=None, window=250):
    """Find the exact/opening candle nearest to a supplied UTC timestamp."""
    dt = entry_time if isinstance(entry_time, datetime) else datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    df = fetch_ohlcv(symbol, timeframe, count=max(100, min(window, 2000)), end_time=dt)
    if df is None or df.empty:
        return None
    # MT5 returns bars whose open time is <= the requested time when end_time is used.
    prior = df[df.index <= pd.Timestamp(dt)]
    if prior.empty:
        return None
    ts = prior.index[-1]
    row = prior.iloc[-1]
    delta_seconds = abs((ts.to_pydatetime() - dt).total_seconds())
    tf_seconds = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400,"1w":604800}.get(timeframe, 3600)
    tolerance = tolerance_minutes if tolerance_minutes is not None else max(1, tf_seconds / 60)
    return {
        "entry_time_utc": dt.isoformat(),
        "entry_candle_ts": ts.to_pydatetime().isoformat(),
        "distance_seconds": round(delta_seconds, 3),
        "within_tolerance": delta_seconds <= tolerance * 60,
        "ohlcv": {k: float(row[k]) for k in ("open", "high", "low", "close", "volume") if k in row.index and pd.notna(row[k])},
        "window": df.loc[:ts].tail(window).reset_index().assign(time=lambda x: x["time"].astype(str)).to_dict("records"),
        "source": "MT5 read-only bridge",
    }
