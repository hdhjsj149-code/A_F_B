"""Twelve Data read-only market-data adapter.

No trading/account endpoints are used. Only public market-data endpoints are
called. The API key is used only for the provider's data quota/authentication.
"""
import os
from datetime import datetime, timezone

import pandas as pd
import requests

BASE_URL = os.getenv("TWELVE_DATA_BASE_URL", "https://api.twelvedata.com").rstrip("/")
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
TIMEOUT = float(os.getenv("TWELVE_DATA_TIMEOUT_SECONDS", "15"))

INTERVALS = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "4h": "4h", "1d": "1day", "1w": "1week",
}

# Twelve Data uses slash notation for FX/precious-metal pairs.
SYMBOL_MAP = {
    "EURUSD": "EUR/USD", "EUR/USD": "EUR/USD",
    "GBPUSD": "GBP/USD", "GBP/USD": "GBP/USD",
    "USDJPY": "USD/JPY", "USD/JPY": "USD/JPY",
    "AUDUSD": "AUD/USD", "AUD/USD": "AUD/USD",
    "USDCHF": "USD/CHF", "USD/CHF": "USD/CHF",
    "USDCAD": "USD/CAD", "USD/CAD": "USD/CAD",
    "NZDUSD": "NZD/USD", "NZD/USD": "NZD/USD",
    "XAUUSD": "XAU/USD", "XAU/USD": "XAU/USD",
    "XAGUSD": "XAG/USD", "XAG/USD": "XAG/USD",
}


def configured():
    return bool(API_KEY)


def normalize_symbol(symbol, market_type="forex"):
    s = str(symbol).strip().upper()
    if s in SYMBOL_MAP:
        return SYMBOL_MAP[s]
    if market_type == "forex" and len(s) == 6 and "/" not in s:
        return f"{s[:3]}/{s[3:]}"
    return s


def _request(endpoint, params):
    if not configured():
        raise RuntimeError("TWELVE_DATA_API_KEY غير مضبوط")
    p = dict(params)
    p["apikey"] = API_KEY
    r = requests.get(f"{BASE_URL}/{endpoint.lstrip('/')}", params=p, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict) and payload.get("status") == "error":
        raise RuntimeError(payload.get("message", "Twelve Data API error"))
    return payload


def fetch_ohlcv(symbol, timeframe="15m", count=500):
    interval = INTERVALS.get(timeframe)
    if not interval:
        raise ValueError(f"Unsupported Twelve Data timeframe: {timeframe}")
    count = max(60, min(int(count), 5000))
    payload = _request("time_series", {
        "symbol": normalize_symbol(symbol),
        "interval": interval,
        "outputsize": count,
        "timezone": "UTC",
        "format": "JSON",
    })
    values = payload.get("values") or []
    if not values:
        return None
    rows = []
    for item in values:
        try:
            rows.append({
                "time": pd.to_datetime(item["datetime"], utc=True),
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": float(item.get("volume", 0) or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        return None
    df = pd.DataFrame(rows).drop_duplicates("time").set_index("time").sort_index()
    df.attrs.update({
        "source": "twelve_data",
        "provider": "Twelve Data",
        "source_symbol": normalize_symbol(symbol),
        "timezone": "UTC",
    })
    return df


def get_last_price(symbol, market_type="forex"):
    payload = _request("price", {"symbol": normalize_symbol(symbol, market_type)})
    value = payload.get("price")
    return float(value) if value is not None else None


def resolve_candle(symbol, timeframe, entry_time, window=250):
    """Resolve to the latest candle opening at/before entry_time, no lookahead."""
    dt = entry_time if isinstance(entry_time, datetime) else datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    df = fetch_ohlcv(symbol, timeframe, count=max(300, min(window + 50, 5000)))
    if df is None or df.empty:
        return None
    prior = df[df.index <= pd.Timestamp(dt)]
    if prior.empty:
        return None
    ts = prior.index[-1]
    row = prior.iloc[-1]
    tf_seconds = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400,"1w":604800}.get(timeframe, 3600)
    distance = abs((ts.to_pydatetime() - dt).total_seconds())
    return {
        "entry_time_utc": dt.isoformat(),
        "entry_candle_ts": ts.to_pydatetime().isoformat(),
        "distance_seconds": round(distance, 3),
        "within_tolerance": distance <= tf_seconds,
        "ohlcv": {k: float(row[k]) for k in ("open", "high", "low", "close", "volume") if k in row and pd.notna(row[k])},
        "window": prior.tail(window).reset_index().assign(time=lambda x: x["time"].astype(str)).to_dict("records"),
        "source": "twelve_data",
        "provider": "Twelve Data",
        "source_symbol": normalize_symbol(symbol),
    }
