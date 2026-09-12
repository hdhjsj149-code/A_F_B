# Changelog — Ahmed Trading Advisor

## v4 — MT5 Read-Only Market Data + Exact Trade Context

- Added `mt5_connector.py` for authenticated, read-only HTTP market data.
- Added `mt5_bridge.py` for the Windows/VPS MT5 terminal.
- Added `MT5_BRIDGE_SETUP.md` with secure deployment guidance.
- Added exact UTC trade timestamp support.
- Added historical candle resolution and mismatch warnings.
- Added OHLCV/pre-entry window capture for journaled trades.
- Added deterministic candlestick pattern detection.
- Added swing structure, basic BOS/HH/HL/LH/LL and support/resistance zones.
- Added multi-timeframe context around trade entry.
- Added `/mt5status` for the owner/admin.
- Added MT5 to the market selection menu.
- Added persistent trade context columns with non-destructive migrations.
- Hardened PostgreSQL migrations to inspect existing columns before ALTER TABLE, avoiding aborted transactions.
- Kept the learning firewall unchanged: candidate -> backtest -> paper -> owner approval -> active.
- No broker trading/execution API was added.
