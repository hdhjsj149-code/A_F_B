"""Persistent storage.

PostgreSQL is used when DATABASE_URL is configured (Render production).
SQLite remains available only as a local-development fallback.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DATABASE_URL, DATABASE_PATH

_LOCK = threading.RLock()
_USE_POSTGRES = bool(DATABASE_URL)

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


@contextmanager
def get_conn():
    if _USE_POSTGRES:
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is configured")
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DATABASE_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _adapt(sql: str) -> str:
    return sql.replace("?", "%s") if _USE_POSTGRES else sql


def _execute(conn, sql, params=()):
    return conn.execute(_adapt(sql), params)


def _fetchall(cur):
    return [dict(r) for r in cur.fetchall()]


def init_db():
    with _LOCK, get_conn() as conn:
        id_type = "BIGSERIAL PRIMARY KEY" if _USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
        statements = [
            f"""CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, username TEXT, role TEXT NOT NULL DEFAULT 'user',
                active INTEGER NOT NULL DEFAULT 0, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            f"""CREATE TABLE IF NOT EXISTS watchlist (
                id {id_type}, user_id BIGINT NOT NULL, symbol TEXT NOT NULL,
                market_type TEXT NOT NULL, timeframe TEXT NOT NULL DEFAULT '1d', added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, symbol, market_type, timeframe)
            )""",
            f"""CREATE TABLE IF NOT EXISTS signals (
                id {id_type}, symbol TEXT NOT NULL, market_type TEXT NOT NULL,
                timeframe TEXT NOT NULL DEFAULT '1d', chat_id BIGINT, message_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, price_at_signal DOUBLE PRECISION,
                composite_score DOUBLE PRECISION, direction TEXT NOT NULL DEFAULT 'NEUTRAL',
                indicators_json TEXT, context_json TEXT, model_version INTEGER, status TEXT NOT NULL DEFAULT 'pending',
                evaluated_at TIMESTAMP, outcome_pct DOUBLE PRECISION
            )""",
            f"""CREATE TABLE IF NOT EXISTS trades (
                id {id_type}, user_id BIGINT NOT NULL, symbol TEXT NOT NULL,
                market_type TEXT NOT NULL, timeframe TEXT NOT NULL, direction TEXT NOT NULL,
                entry_price DOUBLE PRECISION NOT NULL, stop_loss DOUBLE PRECISION,
                take_profit DOUBLE PRECISION, opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP, status TEXT NOT NULL DEFAULT 'open',
                exit_price DOUBLE PRECISION, pnl_pct DOUBLE PRECISION, rr DOUBLE PRECISION,
                reason TEXT, market_context_json TEXT, user_notes TEXT,
                entry_time_utc TIMESTAMP, entry_candle_ts TIMESTAMP, data_source TEXT
            )""",
            f"""CREATE TABLE IF NOT EXISTS trade_outcomes (
                id {id_type}, trade_id BIGINT NOT NULL, outcome TEXT NOT NULL,
                exit_price DOUBLE PRECISION, pnl_pct DOUBLE PRECISION, max_favorable_pct DOUBLE PRECISION,
                max_adverse_pct DOUBLE PRECISION, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS weights (
                indicator_name TEXT PRIMARY KEY, weight DOUBLE PRECISION NOT NULL,
                version INTEGER NOT NULL DEFAULT 1, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            f"""CREATE TABLE IF NOT EXISTS expert_notes (
                id {id_type}, added_by BIGINT, note_text TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            f"""CREATE TABLE IF NOT EXISTS knowledge_items (
                id {id_type}, added_by BIGINT, title TEXT NOT NULL,
                content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general',
                confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5, source TEXT,
                times_tested INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            f"""CREATE TABLE IF NOT EXISTS learning_runs (
                id {id_type}, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP, samples INTEGER NOT NULL DEFAULT 0,
                old_version INTEGER, new_version INTEGER, changed INTEGER NOT NULL DEFAULT 0,
                summary TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS model_versions (
                version INTEGER PRIMARY KEY, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                weights_json TEXT NOT NULL, reason TEXT, backtest_summary TEXT,
                accepted INTEGER NOT NULL DEFAULT 0,
                stage TEXT NOT NULL DEFAULT 'ACTIVE', status TEXT NOT NULL DEFAULT 'active',
                validated_ok INTEGER NOT NULL DEFAULT 0, paper_summary TEXT, parent_version INTEGER
            )""",
            f"""CREATE TABLE IF NOT EXISTS paper_trades (
                id {id_type}, model_version INTEGER NOT NULL, symbol TEXT NOT NULL,
                market_type TEXT NOT NULL, timeframe TEXT NOT NULL, direction TEXT NOT NULL,
                entry_price DOUBLE PRECISION, exit_price DOUBLE PRECISION, pnl_pct DOUBLE PRECISION,
                status TEXT NOT NULL DEFAULT 'open', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP, context_json TEXT
            )""",
            f"""CREATE TABLE IF NOT EXISTS memory_snapshots (
                id {id_type}, snapshot_type TEXT NOT NULL, created_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, payload_json TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS api_key_status (
                key_index INTEGER PRIMARY KEY, disabled_until TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)""",
            f"""CREATE TABLE IF NOT EXISTS audit_log (
                id {id_type}, user_id BIGINT, action TEXT NOT NULL,
                details_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
        ]
        for stmt in statements:
            _execute(conn, stmt)

        # Non-destructive migrations for databases created by older bot versions.
        if _USE_POSTGRES:
            def _pg_columns(table):
                rows = _fetchall(_execute(conn, "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s", (table,)))
                return {r["column_name"] for r in rows}
            model_existing = _pg_columns("model_versions")
            for col, ddl in [("stage", "TEXT NOT NULL DEFAULT 'ACTIVE'"), ("status", "TEXT NOT NULL DEFAULT 'active'"), ("validated_ok", "INTEGER NOT NULL DEFAULT 0"), ("paper_summary", "TEXT"), ("parent_version", "INTEGER")]:
                if col not in model_existing:
                    _execute(conn, f"ALTER TABLE model_versions ADD COLUMN {col} {ddl}")
            trade_existing = _pg_columns("trades")
            for col, ddl in [("entry_time_utc", "TIMESTAMP"), ("entry_candle_ts", "TIMESTAMP"), ("data_source", "TEXT")]:
                if col not in trade_existing:
                    _execute(conn, f"ALTER TABLE trades ADD COLUMN {col} {ddl}")
        else:
            signal_existing = {r["name"] for r in _fetchall(_execute(conn, "PRAGMA table_info(signals)"))}
            if "model_version" not in signal_existing:
                _execute(conn, "ALTER TABLE signals ADD COLUMN model_version INTEGER")
            trade_existing = {r["name"] for r in _fetchall(_execute(conn, "PRAGMA table_info(trades)"))}
            for col, ddl in [("entry_time_utc", "TIMESTAMP"), ("entry_candle_ts", "TIMESTAMP"), ("data_source", "TEXT")]:
                if col not in trade_existing:
                    _execute(conn, f"ALTER TABLE trades ADD COLUMN {col} {ddl}")
            existing = {r["name"] for r in _fetchall(_execute(conn, "PRAGMA table_info(model_versions)"))}
            for col, ddl in [("stage", "TEXT NOT NULL DEFAULT 'ACTIVE'"), ("status", "TEXT NOT NULL DEFAULT 'active'"), ("validated_ok", "INTEGER NOT NULL DEFAULT 0"), ("paper_summary", "TEXT"), ("parent_version", "INTEGER")]:
                if col not in existing:
                    _execute(conn, f"ALTER TABLE model_versions ADD COLUMN {col} {ddl}")

        defaults = {"rsi": 0.20, "macd": 0.20, "bollinger": 0.15, "volume": 0.15, "trend": 0.15, "momentum": 0.15}
        for name, weight in defaults.items():
            if _USE_POSTGRES:
                _execute(conn, "INSERT INTO weights (indicator_name, weight) VALUES (%s, %s) ON CONFLICT (indicator_name) DO NOTHING", (name, weight))
            else:
                _execute(conn, "INSERT OR IGNORE INTO weights (indicator_name, weight) VALUES (?, ?)", (name, weight))

        count = _execute(conn, "SELECT COUNT(*) AS n FROM model_versions").fetchone()["n"]
        if not count:
            weights = get_weights(conn)
            _insert_model_version(conn, 1, weights, "baseline", "No learning yet", 1)

        # Seed a compact, neutral curriculum once. It is guidance for chart vision,
        # not a promise that any pattern will predict price.
        seed = [
            ("Market Structure", "Higher highs/lows suggest bullish structure; lower highs/lows suggest bearish structure. Confirm breaks and avoid treating one wick as a structural break."),
            ("Support Resistance", "Use repeated reactions and closes, not a single exact pixel/price. Treat levels as zones and look for rejection or acceptance."),
            ("Candlesticks", "Engulfing, pin bars, doji and star formations require context; a candle pattern alone is not a trade signal."),
            ("Chart Patterns", "Triangles, flags, wedges, double tops/bottoms and head-and-shoulders require a clear boundary and confirmation; avoid forcing a pattern onto noisy price action."),
            ("Breakouts", "A breakout is stronger when the candle closes beyond a zone and participation/volume supports it. Watch for retests and false breakouts."),
            ("Trend", "Use multiple timeframes when available. A lower-timeframe setup against a strong higher-timeframe trend has higher uncertainty."),
            ("Momentum", "RSI/MACD describe momentum and regime; overbought is not automatically a sell and oversold is not automatically a buy."),
            ("Volume", "Volume can confirm or weaken a move, but crypto/forex volume sources differ. Treat volume context according to the data source."),
            ("Volatility", "ATR-like volatility concepts help place stops and judge whether a target is realistic. High volatility means wider uncertainty."),
            ("Fibonacci", "Retracement/extension levels are reference zones, not guarantees. Use them only when the swing points are clear."),
            ("Wyckoff", "Accumulation, distribution, springs and upthrusts are hypotheses about supply/demand; require price/volume confirmation."),
            ("Risk Management", "Every setup needs an invalidation level. Prefer positive expected value and controlled risk; never infer position size from confidence alone."),
            ("No Hallucination", "If the image does not show enough candles, prices, timeframe or indicators, explicitly say what is unknown instead of inventing levels or patterns."),
        ]
        for title, content in seed:
            if _USE_POSTGRES:
                _execute(conn, "INSERT INTO knowledge_items (added_by, title, content, category, confidence, source) SELECT NULL, %s, %s, %s, %s, %s WHERE NOT EXISTS (SELECT 1 FROM knowledge_items WHERE title=%s)", (title, content, "core", 0.5, "built-in curriculum", title))
            else:
                _execute(conn, "INSERT OR IGNORE INTO knowledge_items (added_by, title, content, category, confidence, source) VALUES (?, ?, ?, ?, ?, ?)", (None, title, content, "core", 0.5, "built-in curriculum"))

def _next_id(conn, table):
    if _USE_POSTGRES:
        return None
    row = _execute(conn, f"SELECT COALESCE(MAX(id), 0) + 1 AS n FROM {table}").fetchone()
    return row["n"]


def _insert_with_id(conn, table, columns, values):
    if _USE_POSTGRES:
        cols = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(values))
        cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) RETURNING id", values)
        return cur.fetchone()["id"]
    ident = _next_id(conn, table)
    cols = ", ".join(["id"] + columns)
    vals = (ident,) + tuple(values)
    placeholders = ", ".join(["?"] * len(vals))
    _execute(conn, f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", vals)
    return ident


def _insert_model_version(conn, version, weights, reason, backtest_summary, accepted, stage="ACTIVE", status="active", validated_ok=None, paper_summary=None, parent_version=None):
    if validated_ok is None:
        validated_ok = int(bool(accepted))
    _execute(conn, "INSERT INTO model_versions (version, weights_json, reason, backtest_summary, accepted, stage, status, validated_ok, paper_summary, parent_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (version, json.dumps(weights), reason, backtest_summary, int(accepted), stage, status, int(validated_ok), paper_summary, parent_version))


def upsert_user(user_id, username):
    with _LOCK, get_conn() as conn:
        role = "owner" if str(user_id) == str(__import__('config').OWNER_USER_ID) else "user"
        active = 1 if role == "owner" else 0
        if _USE_POSTGRES:
            _execute(conn, "INSERT INTO users (user_id, username, role, active) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username=EXCLUDED.username", (user_id, username, role, active))
        else:
            _execute(conn, "INSERT OR IGNORE INTO users (user_id, username, role, active) VALUES (?, ?, ?, ?)", (user_id, username, role, active))
            _execute(conn, "UPDATE users SET username=? WHERE user_id=?", (username, user_id))


def is_active_user(user_id):
    from config import OWNER_USER_ID, ALLOWED_USER_IDS
    if user_id == OWNER_USER_ID or user_id in ALLOWED_USER_IDS:
        return True
    with get_conn() as conn:
        row = _execute(conn, "SELECT active FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["active"])


def is_admin(user_id):
    from config import ADMIN_USER_IDS, OWNER_USER_ID
    return user_id == OWNER_USER_ID or user_id in ADMIN_USER_IDS


def set_user_active(user_id, active=True, role="user"):
    with _LOCK, get_conn() as conn:
        if _USE_POSTGRES:
            _execute(conn, "INSERT INTO users (user_id, role, active) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET role=EXCLUDED.role, active=EXCLUDED.active", (user_id, role, int(active)))
        else:
            _execute(conn, "INSERT OR IGNORE INTO users (user_id, role, active) VALUES (?, ?, ?)", (user_id, role, int(active)))
            _execute(conn, "UPDATE users SET role=?, active=? WHERE user_id=?", (role, int(active), user_id))


def list_users():
    with get_conn() as conn:
        return _fetchall(_execute(conn, "SELECT user_id, username, role, active, joined_at FROM users ORDER BY joined_at DESC"))


def add_to_watchlist(user_id, symbol, market_type, timeframe="1d"):
    with _LOCK, get_conn() as conn:
        try:
            _insert_with_id(conn, "watchlist", ["user_id", "symbol", "market_type", "timeframe"], (user_id, symbol.upper(), market_type, timeframe))
            return True
        except Exception:
            return False


def remove_from_watchlist(user_id, symbol, timeframe=None):
    with _LOCK, get_conn() as conn:
        if timeframe:
            cur = _execute(conn, "DELETE FROM watchlist WHERE user_id=? AND symbol=? AND timeframe=?", (user_id, symbol.upper(), timeframe))
        else:
            cur = _execute(conn, "DELETE FROM watchlist WHERE user_id=? AND symbol=?", (user_id, symbol.upper()))
        return cur.rowcount > 0


def get_user_watchlist(user_id):
    with get_conn() as conn:
        return _fetchall(_execute(conn, "SELECT symbol, market_type, timeframe FROM watchlist WHERE user_id=? ORDER BY added_at", (user_id,)))


def get_all_watched_symbols():
    with get_conn() as conn:
        return _fetchall(_execute(conn, "SELECT DISTINCT symbol, market_type, timeframe FROM watchlist"))


def get_watchers_of(symbol, market_type, timeframe="1d"):
    with get_conn() as conn:
        rows = _fetchall(_execute(conn, "SELECT DISTINCT user_id FROM watchlist WHERE symbol=? AND market_type=? AND timeframe=?", (symbol.upper(), market_type, timeframe)))
        return [r["user_id"] for r in rows if is_active_user(r["user_id"])]


def save_signal(symbol, market_type, chat_id, message_id, price, score, indicators, timeframe="1d", direction="NEUTRAL", context=None, model_version=None):
    with _LOCK, get_conn() as conn:
        if model_version is None:
            active = get_active_model_version()
            model_version = active["version"] if active else 1
        return _insert_with_id(conn, "signals", ["symbol", "market_type", "timeframe", "chat_id", "message_id", "price_at_signal", "composite_score", "direction", "indicators_json", "context_json", "model_version"],
                               (symbol.upper(), market_type, timeframe, chat_id, message_id, price, score, direction, json.dumps(indicators), json.dumps(context or {}), model_version))


def get_pending_signals_older_than(cutoff_iso):
    with get_conn() as conn:
        return _fetchall(_execute(conn, "SELECT * FROM signals WHERE status='pending' AND created_at <= ?", (cutoff_iso,)))


def set_signal_outcome(signal_id, status, outcome_pct=None):
    with _LOCK, get_conn() as conn:
        _execute(conn, "UPDATE signals SET status=?, outcome_pct=?, evaluated_at=CURRENT_TIMESTAMP WHERE id=?", (status, outcome_pct, signal_id))


def get_signal(signal_id):
    with get_conn() as conn:
        row = _execute(conn, "SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
        return dict(row) if row else None


def get_labeled_signals():
    with get_conn() as conn:
        return _fetchall(_execute(conn, "SELECT * FROM signals WHERE status IN ('correct','incorrect')"))


def get_weights(conn=None):
    if conn is not None:
        return {r["indicator_name"]: r["weight"] for r in _fetchall(_execute(conn, "SELECT indicator_name, weight FROM weights"))}
    with get_conn() as c:
        return {r["indicator_name"]: r["weight"] for r in _fetchall(_execute(c, "SELECT indicator_name, weight FROM weights"))}


def create_candidate_model(weights, reason="continuous_learning", parent_version=None):
    with _LOCK, get_conn() as conn:
        row = _execute(conn, "SELECT COALESCE(MAX(version),1) AS v FROM model_versions").fetchone()
        new_version = int(row["v"]) + 1
        _insert_model_version(conn, new_version, weights, reason, "Awaiting backtesting", 0, stage="BACKTEST", status="pending", validated_ok=0, parent_version=parent_version)
        return new_version


def get_active_model_version():
    with get_conn() as conn:
        row = _execute(conn, "SELECT * FROM model_versions WHERE accepted=1 AND stage='ACTIVE' ORDER BY version DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def get_latest_candidate(stage=None):
    with get_conn() as conn:
        if stage:
            row = _execute(conn, "SELECT * FROM model_versions WHERE accepted=0 AND stage=? ORDER BY version DESC LIMIT 1", (stage,)).fetchone()
        else:
            row = _execute(conn, "SELECT * FROM model_versions WHERE accepted=0 AND stage <> 'ARCHIVED' ORDER BY version DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def get_model_version(version):
    with get_conn() as conn:
        row = _execute(conn, "SELECT * FROM model_versions WHERE version=?", (version,)).fetchone()
        return dict(row) if row else None


def update_model_validation(version, stage, status, validated_ok=False, backtest_summary=None, paper_summary=None):
    with _LOCK, get_conn() as conn:
        _execute(conn, "UPDATE model_versions SET stage=?, status=?, validated_ok=?, backtest_summary=COALESCE(?, backtest_summary), paper_summary=COALESCE(?, paper_summary) WHERE version=?", (stage, status, int(validated_ok), backtest_summary, paper_summary, version))


def activate_model_version(version):
    with _LOCK, get_conn() as conn:
        row = _execute(conn, "SELECT weights_json FROM model_versions WHERE version=?", (version,)).fetchone()
        if not row:
            raise ValueError("model version not found")
        weights = json.loads(row["weights_json"])
        _execute(conn, "UPDATE model_versions SET accepted=0, stage='ARCHIVED', status='archived' WHERE accepted=1")
        _execute(conn, "UPDATE model_versions SET accepted=1, stage='ACTIVE', status='active' WHERE version=?", (version,))
        # Only here, after all gates, do weights reach the live engine.
        current_version = int(version)
        for name, weight in weights.items():
            if _USE_POSTGRES:
                _execute(conn, "INSERT INTO weights (indicator_name, weight, version) VALUES (?, ?, ?) ON CONFLICT(indicator_name) DO UPDATE SET weight=EXCLUDED.weight, version=EXCLUDED.version, updated_at=CURRENT_TIMESTAMP", (name, weight, current_version))
            else:
                _execute(conn, "INSERT OR REPLACE INTO weights (indicator_name, weight, version, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (name, weight, current_version))


def set_weights(weights, reason="learning"):
    """Backward-compatible API: creates a candidate only; it NEVER changes live weights."""
    parent = get_active_model_version()
    return create_candidate_model(weights, reason, parent["version"] if parent else None)

def create_paper_trade(model_version, symbol, market_type, timeframe, direction, entry_price, context=None):
    with _LOCK, get_conn() as conn:
        return _insert_with_id(conn, "paper_trades", ["model_version", "symbol", "market_type", "timeframe", "direction", "entry_price", "context_json"], (model_version, symbol.upper(), market_type, timeframe, direction.upper(), entry_price, json.dumps(context or {})))

def close_paper_trade(paper_id, exit_price, pnl_pct, outcome):
    with _LOCK, get_conn() as conn:
        _execute(conn, "UPDATE paper_trades SET status='closed', exit_price=?, pnl_pct=?, closed_at=CURRENT_TIMESTAMP WHERE id=? AND status='open'", (exit_price, pnl_pct, paper_id))

def get_paper_trades(model_version, status='closed'):
    with get_conn() as conn:
        return _fetchall(_execute(conn, "SELECT * FROM paper_trades WHERE model_version=? AND status=? ORDER BY created_at", (model_version, status)))


def add_expert_note(admin_id, text, category="general"):
    with _LOCK, get_conn() as conn:
        return _insert_with_id(conn, "expert_notes", ["added_by", "note_text", "category"], (admin_id, text, category))


def get_expert_notes(limit=50):
    with get_conn() as conn:
        rows = _fetchall(_execute(conn, "SELECT note_text FROM expert_notes ORDER BY created_at DESC LIMIT ?", (limit,)))
        return [r["note_text"] for r in rows]


def add_knowledge(added_by, title, content, category="general", confidence=0.5, source=None):
    with _LOCK, get_conn() as conn:
        return _insert_with_id(conn, "knowledge_items", ["added_by", "title", "content", "category", "confidence", "source"], (added_by, title, content, category, confidence, source))


def get_knowledge(limit=100, category=None):
    with get_conn() as conn:
        if category:
            return _fetchall(_execute(conn, "SELECT * FROM knowledge_items WHERE active=1 AND category=? ORDER BY updated_at DESC LIMIT ?", (category, limit)))
        return _fetchall(_execute(conn, "SELECT * FROM knowledge_items WHERE active=1 ORDER BY updated_at DESC LIMIT ?", (limit,)))


def record_trade(user_id, symbol, market_type, timeframe, direction, entry_price, stop_loss=None, take_profit=None, reason=None, context=None, user_notes=None, entry_time_utc=None, entry_candle_ts=None, data_source=None):
    with _LOCK, get_conn() as conn:
        rr = None
        if stop_loss is not None and take_profit is not None and entry_price:
            risk = abs(entry_price - stop_loss)
            reward = abs(take_profit - entry_price)
            if risk > 0:
                rr = reward / risk
        return _insert_with_id(conn, "trades", ["user_id", "symbol", "market_type", "timeframe", "direction", "entry_price", "stop_loss", "take_profit", "reason", "market_context_json", "user_notes", "rr", "entry_time_utc", "entry_candle_ts", "data_source"],
                               (user_id, symbol.upper(), market_type, timeframe, direction.upper(), entry_price, stop_loss, take_profit, reason, json.dumps(context or {}), user_notes, rr, entry_time_utc, entry_candle_ts, data_source))


def get_open_trades(user_id=None):
    with get_conn() as conn:
        if user_id is None:
            return _fetchall(_execute(conn, "SELECT * FROM trades WHERE status='open' ORDER BY opened_at DESC"))
        return _fetchall(_execute(conn, "SELECT * FROM trades WHERE user_id=? AND status='open' ORDER BY opened_at DESC", (user_id,)))


def close_trade(trade_id, user_id, outcome, exit_price=None, pnl_pct=None, notes=None, max_favorable_pct=None, max_adverse_pct=None):
    with _LOCK, get_conn() as conn:
        row = _execute(conn, "SELECT * FROM trades WHERE id=? AND user_id=? AND status='open'", (trade_id, user_id)).fetchone()
        if not row:
            return False
        if pnl_pct is None and exit_price is not None:
            sign = 1 if row["direction"] == "BUY" else -1
            pnl_pct = ((exit_price - row["entry_price"]) / row["entry_price"]) * 100 * sign
        _execute(conn, "UPDATE trades SET status='closed', closed_at=CURRENT_TIMESTAMP, exit_price=?, pnl_pct=? WHERE id=?", (exit_price, pnl_pct, trade_id))
        _insert_with_id(conn, "trade_outcomes", ["trade_id", "outcome", "exit_price", "pnl_pct", "max_favorable_pct", "max_adverse_pct", "notes"], (trade_id, outcome.upper(), exit_price, pnl_pct, max_favorable_pct, max_adverse_pct, notes))
        return True


def get_closed_trades(user_id=None):
    with get_conn() as conn:
        if user_id is None:
            return _fetchall(_execute(conn, "SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC"))
        return _fetchall(_execute(conn, "SELECT * FROM trades WHERE user_id=? AND status='closed' ORDER BY closed_at DESC", (user_id,)))


def get_trade(trade_id, user_id=None):
    with get_conn() as conn:
        if user_id is None:
            row = _execute(conn, "SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        else:
            row = _execute(conn, "SELECT * FROM trades WHERE id=? AND user_id=?", (trade_id, user_id)).fetchone()
        return dict(row) if row else None


def get_trade_stats(user_id=None):
    with get_conn() as conn:
        params = () if user_id is None else (user_id,)
        where = "" if user_id is None else "WHERE user_id=?"
        row = _execute(conn, f"SELECT COUNT(*) AS total, SUM(CASE WHEN status='closed' AND pnl_pct>0 THEN 1 ELSE 0 END) AS wins, SUM(CASE WHEN status='closed' AND pnl_pct<=0 THEN 1 ELSE 0 END) AS losses, COALESCE(AVG(CASE WHEN status='closed' THEN pnl_pct END),0) AS avg_pnl FROM trades {where}", params).fetchone()
        return dict(row)


def get_learning_stats():
    with get_conn() as conn:
        return {
            "trades": _execute(conn, "SELECT COUNT(*) AS n FROM trades").fetchone()["n"],
            "closed_trades": _execute(conn, "SELECT COUNT(*) AS n FROM trades WHERE status='closed'").fetchone()["n"],
            "signals": _execute(conn, "SELECT COUNT(*) AS n FROM signals").fetchone()["n"],
            "labeled_signals": _execute(conn, "SELECT COUNT(*) AS n FROM signals WHERE status IN ('correct','incorrect')").fetchone()["n"],
            "knowledge": _execute(conn, "SELECT COUNT(*) AS n FROM knowledge_items WHERE active=1").fetchone()["n"],
            "model_version": _execute(conn, "SELECT COALESCE(MAX(version),1) AS n FROM model_versions WHERE accepted=1").fetchone()["n"],
            "candidate_versions": _execute(conn, "SELECT COUNT(*) AS n FROM model_versions WHERE accepted=0 AND stage <> 'ARCHIVED'").fetchone()["n"],
            "snapshots": _execute(conn, "SELECT COUNT(*) AS n FROM memory_snapshots").fetchone()["n"],
        }


def add_learning_run(samples, old_version, new_version, changed, summary):
    with _LOCK, get_conn() as conn:
        return _insert_with_id(conn, "learning_runs", ["samples", "old_version", "new_version", "changed", "summary", "finished_at"], (samples, old_version, new_version, int(changed), summary, _utcnow()))


def add_audit(user_id, action, details=None):
    with _LOCK, get_conn() as conn:
        _insert_with_id(conn, "audit_log", ["user_id", "action", "details_json"], (user_id, action, json.dumps(details or {})))


def get_model_history(limit=20):
    with get_conn() as conn:
        return _fetchall(_execute(conn, "SELECT version, created_at, reason, backtest_summary, paper_summary, accepted, stage, status, validated_ok, parent_version FROM model_versions ORDER BY version DESC LIMIT ?", (limit,)))


def create_memory_snapshot(snapshot_type="manual", created_by=None):
    """Create a self-contained DB snapshot of learning memory inside persistent storage.
    This is non-destructive and survives application redeploys because it lives in PostgreSQL.
    """
    with _LOCK, get_conn() as conn:
        payload = {
            "weights": get_weights(conn),
            "models": _fetchall(_execute(conn, "SELECT * FROM model_versions ORDER BY version")),
            "knowledge": _fetchall(_execute(conn, "SELECT * FROM knowledge_items ORDER BY id")),
            "learning_runs": _fetchall(_execute(conn, "SELECT * FROM learning_runs ORDER BY id")),
        }
        return _insert_with_id(conn, "memory_snapshots", ["snapshot_type", "created_by", "payload_json"], (snapshot_type, created_by, json.dumps(payload, default=str)))

def get_snapshot_stats():
    with get_conn() as conn:
        row = _execute(conn, "SELECT COUNT(*) AS n, MAX(created_at) AS latest FROM memory_snapshots").fetchone()
        return dict(row)


def disable_key_temporarily(key_index, until_iso):
    with _LOCK, get_conn() as conn:
        if _USE_POSTGRES:
            _execute(conn, "INSERT INTO api_key_status (key_index, disabled_until) VALUES (?, ?) ON CONFLICT(key_index) DO UPDATE SET disabled_until=EXCLUDED.disabled_until", (key_index, until_iso))
        else:
            _execute(conn, "INSERT OR REPLACE INTO api_key_status (key_index, disabled_until) VALUES (?, ?)", (key_index, until_iso))


def get_disabled_until(key_index):
    with get_conn() as conn:
        row = _execute(conn, "SELECT disabled_until FROM api_key_status WHERE key_index=?", (key_index,)).fetchone()
        return row["disabled_until"] if row else None


def get_meta(key, default=None):
    with get_conn() as conn:
        row = _execute(conn, "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_meta(key, value):
    with _LOCK, get_conn() as conn:
        if _USE_POSTGRES:
            _execute(conn, "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (key, str(value)))
        else:
            _execute(conn, "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))
