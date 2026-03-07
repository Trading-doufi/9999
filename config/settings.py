# config/settings.py
import os

# ========== TELEGRAM ==========
TELEGRAM_TOKEN   = "8519191243:AAG8nt2H3ceZktZmx5iPlKDJkK4i5OI7X30"
TELEGRAM_CHAT_ID = "-4845936021"

# ========== BYBIT ==========
BYBIT_API_KEY    = "hkosl5qIgSou4H8AfF"
BYBIT_API_SECRET = "M3miXpAHGdZ9i1eO3B7EU5N4F2WGmNOBlnkz"
BYBIT_WS_URL     = "wss://stream.bybit.com/v5/public/linear"

# ========== KAFKA ==========
KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"

# ========== REDIS ==========
REDIS_HOST = "localhost"
REDIS_PORT = 6379

# ========== MONGODB ==========
MONGODB_URI = "mongodb+srv://shopdoufi_db_user:qsUnASiHG2XUcj2p@trading.hfo9ojn.mongodb.net/?appName=trading"
MONGODB_DB  = "trading_bot"

# ========== TRADING SETTINGS ==========
SYMBOLS = [
    # الكبار — ليكويديتي ممتاز
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",

    # Layer 2 + DeFi
    "ARBUSDT", "OPUSDT", "NEARUSDT", "APTUSDT", "AAVEUSDT",
    "UNIUSDT", "CRVUSDT", "DYDXUSDT", "SNXUSDT", "COMPUSDT",

    # عملات أثبتت أداء من اللوقز
    "PHAUSDT", "FORMUSDT", "RIVERUSDT", "AIXBTUSDT", "STXUSDT",
    "PIPPINUSDT", "1000RATSUSDT", "AKTUSDT", "YFIUSDT", "ATOMUSDT",

    # عملات جديدة
    "QNTUSDT", "AGIUSDT", "ROBOUSDT", "SAHARAUSDT"
]

MIN_SCORE = 85

# ========== PATHS ==========
LOG_DIR  = "logs"
DATA_DIR = "data"
