"""Deterministic market-context engine for trade journaling.

It resolves a trade to the nearest real MT5 candle and stores structured,
reproducible context. AI is not used for this step.
"""
from datetime import datetime, timezone
import numpy as np
import pandas as pd

import data_fetcher
import indicators

TF_CHAIN = {
    "1m": ["1m", "5m", "15m"], "5m": ["5m", "15m", "1h"],
    "15m": ["15m", "1h", "4h"], "30m": ["30m", "1h", "4h"],
    "1h": ["1h", "4h", "1d"], "4h": ["4h", "1d", "1w"],
    "1d": ["1d", "1w"], "1w": ["1w"],
}


def parse_utc(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        # Never silently assume local server time. Command input is UTC.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _candle_patterns(df):
    if df is None or len(df) < 3:
        return []
    d = df.astype(float).copy()
    o, h, l, c = d.open, d.high, d.low, d.close
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    names = []
    i = -1
    if body.iloc[i] / rng.iloc[i] <= 0.10:
        names.append("Doji")
    if lower.iloc[i] >= body.iloc[i] * 2 and upper.iloc[i] <= body.iloc[i] * 0.8 and c.iloc[i] > o.iloc[i]:
        names.append("Hammer")
    if upper.iloc[i] >= body.iloc[i] * 2 and lower.iloc[i] <= body.iloc[i] * 0.8 and c.iloc[i] < o.iloc[i]:
        names.append("Shooting Star")
    if c.iloc[i-1] < o.iloc[i-1] and c.iloc[i] > o.iloc[i] and o.iloc[i] <= c.iloc[i-1] and c.iloc[i] >= o.iloc[i-1]:
        names.append("Bullish Engulfing")
    if c.iloc[i-1] > o.iloc[i-1] and c.iloc[i] < o.iloc[i] and o.iloc[i] >= c.iloc[i-1] and c.iloc[i] <= o.iloc[i-1]:
        names.append("Bearish Engulfing")
    if len(d) >= 5:
        b1, b2, b3 = body.iloc[-3], body.iloc[-2], body.iloc[-1]
        midpoint1 = (o.iloc[-3] + c.iloc[-3]) / 2
        small = b2 <= (h.iloc[-3] - l.iloc[-3]) * 0.35
        if c.iloc[-3] < o.iloc[-3] and small and c.iloc[-1] > o.iloc[-1] and c.iloc[-1] > midpoint1:
            names.append("Morning Star")
        if c.iloc[-3] > o.iloc[-3] and small and c.iloc[-1] < o.iloc[-1] and c.iloc[-1] < midpoint1:
            names.append("Evening Star")
    return names


def _swings(df, lookback=3):
    h, l = df.high.astype(float), df.low.astype(float)
    swing_high, swing_low = [], []
    for i in range(lookback, len(df) - lookback):
        if h.iloc[i] == h.iloc[i-lookback:i+lookback+1].max():
            swing_high.append((df.index[i], float(h.iloc[i])))
        if l.iloc[i] == l.iloc[i-lookback:i+lookback+1].min():
            swing_low.append((df.index[i], float(l.iloc[i])))
    return swing_high, swing_low


def _structure(df):
    sh, sl = _swings(df)
    labels = []
    for items, kind in ((sh, "H"), (sl, "L")):
        for j in range(1, len(items)):
            prev, cur = items[j-1][1], items[j][1]
            labels.append((items[j][0].isoformat(), ("HH" if cur > prev else "LH") if kind == "H" else ("HL" if cur > prev else "LL")))
    labels.sort(key=lambda x: x[0])
    recent = labels[-6:]
    last_high = sh[-1][1] if sh else None
    last_low = sl[-1][1] if sl else None
    close = float(df.close.iloc[-1])
    bos = "BULLISH_BOS" if last_high is not None and close > last_high else "BEARISH_BOS" if last_low is not None and close < last_low else None
    return {"recent_swings": recent, "bias": "BULLISH" if recent and recent[-1][1] in ("HH", "HL") else "BEARISH" if recent and recent[-1][1] in ("LH", "LL") else "NEUTRAL", "bos": bos}


def _zones(df, n=8):
    sh, sl = _swings(df)
    vals = [x[1] for x in sh[-n:]] + [x[1] for x in sl[-n:]]
    if not vals:
        return []
    # Cluster nearby pivots; tolerance is 0.25% of price, capped by observed range.
    price = float(df.close.iloc[-1])
    tol = max(price * 0.0025, (float(df.high.max()) - float(df.low.min())) * 0.005)
    clusters = []
    for v in sorted(vals):
        if not clusters or abs(v - clusters[-1][-1]) > tol:
            clusters.append([v])
        else:
            clusters[-1].append(v)
    return [{"level": round(float(np.mean(c)), 8), "touches": len(c)} for c in clusters if len(c) >= 2]


def _context_for_df(df):
    if df is None or len(df) < 60:
        return None
    score, strengths, direction, confidence = indicators.compute_composite_score(df)
    return {
        "bars": int(len(df)),
        "indicator_score": score,
        "indicator_strengths": strengths,
        "direction": direction,
        "confidence": confidence,
        "candlestick_patterns": _candle_patterns(df.tail(20)),
        "structure": _structure(df.tail(min(len(df), 250))),
        "support_resistance_zones": _zones(df.tail(min(len(df), 300))),
    }


def resolve_trade_context(symbol, market_type, timeframe, entry_time, entry_price=None):
    """Resolve a trade timestamp to a candle and collect multi-TF evidence.

    Returns a warning instead of pretending an exact match when the timestamp
    is outside the candle tolerance.
    """
    dt = parse_utc(entry_time)
    resolved_source = data_fetcher._selected_source(market_type)
    result = {"source": resolved_source, "requested_market_type": market_type, "entry_time_utc": dt.isoformat(), "exact": False, "warnings": []}
    resolved = data_fetcher.resolve_candle(symbol, market_type, timeframe, dt, window=250)
    if not resolved:
        result["warnings"].append("تعذر العثور على شمعة MT5 مطابقة للوقت المحدد.")
        return result
    result.update({"entry_candle_ts": resolved["entry_candle_ts"], "entry_candle_ohlcv": resolved["ohlcv"], "candle_distance_seconds": resolved["distance_seconds"], "exact": bool(resolved["within_tolerance"]), "pre_entry_window": resolved["window"], "data_source": resolved.get("source"), "provider": resolved.get("provider"), "source_symbol": resolved.get("source_symbol")})
    if not resolved["within_tolerance"]:
        result["warnings"].append("وقت الصفقة بعيد عن أقرب شمعة ضمن هامش الفريم؛ راجع الوقت/المنطقة الزمنية.")

    # Analyze candles ending at the resolved entry candle, never future candles.
    base = pd.DataFrame(resolved.get("window", []))
    if not base.empty:
        base["time"] = pd.to_datetime(base["time"], utc=True, errors="coerce")
        base = base.dropna(subset=["time"]).set_index("time").sort_index().tail(300)
    result["context"] = _context_for_df(base)

    mtf = {}
    source = result.get("data_source")
    for tf in TF_CHAIN.get(timeframe, [timeframe]):
        if tf == timeframe:
            mtf[tf] = result["context"]
            continue
        try:
            if source == "mt5":
                import mt5_connector
                d = mt5_connector.fetch_ohlcv(symbol, timeframe=tf, count=300, end_time=dt)
            elif source == "twelve_data":
                import twelve_data
                d = twelve_data.fetch_ohlcv(symbol, timeframe=tf, count=1000)
            else:
                d = data_fetcher.fetch_ohlcv(symbol, market_type, timeframe=tf, days=30)
            if d is not None:
                d = d[d.index <= pd.Timestamp(dt)].tail(300)
            mtf[tf] = _context_for_df(d)
        except Exception as exc:
            mtf[tf] = None
            result["warnings"].append(f"تعذر جلب {tf}: {exc}")
    result["multi_timeframe"] = mtf
    if entry_price is not None and resolved["ohlcv"]:
        close = float(resolved["ohlcv"].get("close", 0))
        if close:
            result["entry_price_vs_candle_close_pct"] = round((float(entry_price) - close) / close * 100, 5)
    return result
