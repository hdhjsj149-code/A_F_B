"""Technical-analysis engine. No AI is used here."""
import numpy as np
import pandas as pd
import database


def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    line = ema12 - ema26
    signal = line.ewm(span=9, adjust=False).mean()
    return line, signal, line - signal


def _bollinger(close, period=20, mult=2):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + mult * std
    lower = mid - mult * std
    pb = (close - lower) / (upper - lower).replace(0, np.nan)
    return upper, mid, lower, pb


def compute_indicator_strengths(df):
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)
    rsi = float(_rsi(close).iloc[-1]) if not pd.isna(_rsi(close).iloc[-1]) else 50.0
    macd_line, signal_line, hist = _macd(close)
    h = float(hist.iloc[-1])
    h_prev = float(hist.iloc[-2]) if len(hist) > 1 else h
    _, mid, _, pb = _bollinger(close)
    pbv = float(pb.iloc[-1]) if not pd.isna(pb.iloc[-1]) else 0.5
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    trend = 0.5
    if close.iloc[-1] > ema20 > ema50:
        trend = 1.0
    elif close.iloc[-1] < ema20 < ema50:
        trend = 0.0
    else:
        trend = 0.5
    momentum = float(np.clip((close.iloc[-1] / close.iloc[-5] - 0.98) / 0.04, 0, 1)) if len(close) >= 5 else 0.5
    vol_avg = volume.rolling(20).mean().iloc[-1]
    vol_ratio = float(volume.iloc[-1] / vol_avg) if vol_avg and not pd.isna(vol_avg) else 1.0

    # Each factor is represented as bullish strength (0..1).
    rsi_strength = float(np.clip((rsi - 30) / 40, 0, 1))
    macd_strength = 1.0 if h > 0 and h >= h_prev else float(np.clip((h - h_prev) / (abs(h_prev) + 1e-9) + 0.5, 0, 1))
    boll_strength = float(np.clip((pbv - 0.15) / 0.70, 0, 1))
    volume_strength = float(np.clip(0.5 + (0.5 if close.iloc[-1] > close.iloc[-2] else -0.5) * min(max(vol_ratio - 1, 0) / 2, 1), 0, 1))
    return {
        "rsi": round(rsi_strength, 4),
        "macd": round(macd_strength, 4),
        "bollinger": round(boll_strength, 4),
        "volume": round(volume_strength, 4),
        "trend": round(float(trend), 4),
        "momentum": round(momentum, 4),
    }


def compute_composite_score(df):
    strengths = compute_indicator_strengths(df)
    weights = database.get_weights()
    total = sum(weights.get(k, 0) for k in strengths) or 1.0
    score = sum(strengths[k] * weights.get(k, 0) for k in strengths) / total
    direction = "BUY" if score >= 0.60 else "SELL" if score <= 0.40 else "NEUTRAL"
    confidence = abs(score - 0.5) * 2
    return round(score * 100, 1), strengths, direction, round(confidence * 100, 1)


def format_analysis_text(symbol, score, strengths, price, direction="NEUTRAL", confidence=0, timeframe="1d"):
    def bar(v):
        filled = int(max(0, min(10, v * 10)))
        return "🟩" * filled + "⬜" * (10 - filled)
    lines = [
        f"📊 *تحليل {symbol} — {timeframe}*",
        f"السعر: `{price:,.8f}`",
        f"السيناريو: *{direction}*",
        f"الثقة الإحصائية: *{confidence:.1f}%*",
        f"النتيجة: *{score}/100*",
        "",
        f"RSI: {bar(strengths['rsi'])}",
        f"MACD: {bar(strengths['macd'])}",
        f"Bollinger: {bar(strengths['bollinger'])}",
        f"Volume: {bar(strengths['volume'])}",
        f"Trend: {bar(strengths['trend'])}",
        f"Momentum: {bar(strengths['momentum'])}",
        "",
        "⚠️ النتيجة احتمالية وليست ضماناً للربح. لا تُستخدم وحدها لاتخاذ قرار مالي.",
    ]
    return "\n".join(lines)
