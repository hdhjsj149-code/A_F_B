"""Source-aware, read-only market-data engine. No AI and no trade execution."""
import os
import pandas as pd
import yfinance as yf
import ccxt
import mt5_connector
import twelve_data

_binance = ccxt.binance({"enableRateLimit": True})

# auto: Twelve Data for forex/precious metals when configured, otherwise legacy fallback.
# mt5: future Read-Only bridge. twelve_data: force Twelve Data. legacy: old providers.
DATA_SOURCE = os.getenv("MARKET_DATA_SOURCE", "auto").strip().lower()


def _with_source(df, source, provider=None, source_symbol=None):
    if df is not None:
        df.attrs.update({
            "source": source,
            "provider": provider or source,
            "source_symbol": source_symbol,
            "timezone": "UTC",
        })
    return df


def _selected_source(market_type):
    if DATA_SOURCE in {"twelve_data", "mt5", "yfinance", "ccxt"}:
        return DATA_SOURCE
    if market_type == "mt5":
        return "mt5"
    if market_type in {"forex", "stock"} and twelve_data.configured():
        return "twelve_data"
    if market_type == "crypto":
        return "ccxt"
    return "yfinance"


def fetch_ohlcv(symbol, market_type, days=90, timeframe="1d"):
    source = _selected_source(market_type)
    try:
        if source == "twelve_data":
            # Keep requests bounded and useful for Render's free-tier quota.
            count = min(max(100, int(days * 24 * 60 / _tf_minutes(timeframe))), 5000)
            return twelve_data.fetch_ohlcv(symbol, timeframe=timeframe, count=count)
        if source == "mt5":
            return _with_source(mt5_connector.fetch_ohlcv(symbol, timeframe=timeframe, count=min(max(days * 100, 100), 2000)), "mt5", "MT5 Read-Only Bridge", symbol.upper())
        if source == "yfinance":
            return _fetch_yfinance(symbol, days, timeframe)
        if source == "ccxt":
            return _fetch_ccxt(symbol, days, timeframe)
    except Exception:
        # auto mode can safely fall back, but never silently mix sources inside a resolved trade snapshot.
        if DATA_SOURCE == "auto" and source == "twelve_data":
            try:
                return _fetch_yfinance(symbol, days, timeframe)
            except Exception:
                pass
        return None
    return None


def _tf_minutes(timeframe):
    return {"1m":1,"5m":5,"15m":15,"30m":30,"1h":60,"4h":240,"1d":1440,"1w":10080}.get(timeframe, 1440)


def _fetch_yfinance(symbol, days, timeframe):
    ticker = yf.Ticker(symbol)
    allowed = {"1d": "1d", "1h": "1h", "30m": "30m", "15m": "15m", "5m": "5m"}
    interval = allowed.get(timeframe, "1d")
    hist = ticker.history(period=f"{max(days, 30)}d", interval=interval, auto_adjust=False)
    if hist.empty:
        return None
    hist = hist.rename(columns=str.lower)
    cols = ["open", "high", "low", "close", "volume"]
    return _with_source(hist[cols].dropna(), "yfinance", "Yahoo Finance", symbol.upper())


def _fetch_ccxt(symbol, days, timeframe):
    if "/" not in symbol:
        symbol = f"{symbol}/USDT"
    limits = {"1d": 200, "4h": 500, "1h": 500, "15m": 1000, "5m": 1000}
    raw = _binance.fetch_ohlcv(symbol, timeframe=timeframe if timeframe in limits else "1d", limit=min(limits.get(timeframe, 200), 1000))
    if not raw:
        return None
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    return _with_source(df, "binance", "Binance", symbol.upper())


def get_last_price(symbol, market_type, timeframe="1d"):
    source = _selected_source(market_type)
    try:
        if source == "mt5":
            tick = mt5_connector.get_tick(symbol)
            value = tick.get("tick", {}).get("last") or tick.get("tick", {}).get("bid") or tick.get("tick", {}).get("ask")
            return float(value) if value is not None else None
        if source == "twelve_data":
            return twelve_data.get_last_price(symbol, market_type)
        df = fetch_ohlcv(symbol, market_type, days=5, timeframe=timeframe)
        if df is None or df.empty:
            return None
        return float(df["close"].iloc[-1])
    except Exception:
        return None


def resolve_candle(symbol, market_type, timeframe, entry_time, window=250):
    """Source-aware exact candle resolver. Never substitutes another source."""
    source = _selected_source(market_type)
    if source == "mt5":
        return mt5_connector.resolve_candle(symbol, timeframe, entry_time, window=window)
    if source == "twelve_data":
        return twelve_data.resolve_candle(symbol, timeframe, entry_time, window=window)
    # Legacy providers do not promise exact historical matching; return a guarded result.
    df = fetch_ohlcv(symbol, market_type, days=90, timeframe=timeframe)
    if df is None or df.empty:
        return None
    from datetime import datetime, timezone
    dt = entry_time if isinstance(entry_time, datetime) else datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    prior = df[df.index <= pd.Timestamp(dt)]
    if prior.empty:
        return None
    ts = prior.index[-1]
    row = prior.iloc[-1]
    return {
        "entry_time_utc": dt.isoformat(), "entry_candle_ts": ts.to_pydatetime().isoformat(),
        "distance_seconds": abs((ts.to_pydatetime()-dt).total_seconds()), "within_tolerance": False,
        "ohlcv": {k: float(row[k]) for k in ("open","high","low","close","volume") if k in row},
        "window": prior.tail(window).reset_index().rename(columns={prior.index.name or "index":"time"}).to_dict("records"),
        "source": df.attrs.get("source", source), "provider": df.attrs.get("provider", source),
        "source_symbol": df.attrs.get("source_symbol", symbol.upper()),
    }
