@echo off
setlocal
if "%MT5_BRIDGE_TOKEN%"=="" (
  echo ERROR: Set MT5_BRIDGE_TOKEN before starting the bridge.
  echo Example: set MT5_BRIDGE_TOKEN=your-long-random-secret
  exit /b 1
)
set MT5_BRIDGE_HOST=127.0.0.1
set MT5_BRIDGE_PORT=8765
python mt5_bridge.py
