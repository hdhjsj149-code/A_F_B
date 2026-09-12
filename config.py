"""Central configuration for the trading advisory bot."""
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change-this-secret")

# Permanent owner. This is deliberately not optional.
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "7601281598"))

# Future users can be enabled from Ahmed's admin panel.
ADMIN_USER_IDS = {OWNER_USER_ID}
ADMIN_USER_IDS.update(
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
)

# Optional bootstrap allow-list. Owner is always allowed.
ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()
}

GEMINI_API_KEYS = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Render Postgres supplies DATABASE_URL. Keep DATABASE_PATH only as a local-dev fallback.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_memory.db")

SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))
LEARNING_CYCLE_HOURS = int(os.getenv("LEARNING_CYCLE_HOURS", "24"))
OUTCOME_HORIZON_DAYS = int(os.getenv("OUTCOME_HORIZON_DAYS", "5"))
ALERT_SCORE_THRESHOLD = float(os.getenv("ALERT_SCORE_THRESHOLD", "65"))

MARKET_DATA_SOURCE = os.getenv("MARKET_DATA_SOURCE", "auto").strip().lower()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

MARKET_SOURCES = {
    "stock": "twelve_data" if TWELVE_DATA_API_KEY else "yfinance",
    "forex": "twelve_data" if TWELVE_DATA_API_KEY else "yfinance",
    "crypto": "ccxt",
    "mt5": "mt5",
}
