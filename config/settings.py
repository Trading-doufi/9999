# config/settings.py
import os

# ========== TELEGRAM ==========
# من @BotFather
TELEGRAM_TOKEN = "8519191243:AAG8nt2H3ceZktZmx5iPlKDJkK4i5OI7X30"
# من @userinfobot
TELEGRAM_CHAT_ID = "1615885159"

# ========== BYBIT (اختياري - للتوسع) ==========
BYBIT_API_KEY = "hkosl5qIgSou4H8AfF"      # من Bybit Dashboard
BYBIT_API_SECRET = "M3miXpAHGdZ9i1eO3B7EU5N4F2WGmNOBlnkz" # من Bybit Dashboard
BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"

# ========== KAFKA ==========
KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"

# ========== REDIS ==========
REDIS_HOST = "localhost"
REDIS_PORT = 6379

# ========== MONGODB ==========
MONGODB_URI = "mongodb+srv://shopdoufi_db_user:qsUnASiHG2XUcj2p@trading.hfo9ojn.mongodb.net/?appName=trading"
MONGODB_DB = "trading_bot"

# ========== TRADING SETTINGS ==========
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT", "LTCUSDT", "BCHUSDT",
    "ATOMUSDT", "ETCUSDT", "FILUSDT", "ICPUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
    "NEARUSDT", "AAVEUSDT", "ALGOUSDT", "GRTUSDT", "VETUSDT", "THETAUSDT", "XLMUSDT",
    "EGLDUSDT", "FTMUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT", "APEUSDT", "GALAUSDT",
    "ENSUSDT", "CRVUSDT", "SNXUSDT", "COMPUSDT", "MKRUSDT", "YFIUSDT", "SUSHIUSDT",
    "DYDXUSDT", "IMXUSDT", "RNDRUSDT", "STXUSDT", "QNTUSDT", "FLOWUSDT", "MINAUSDT"
]

MIN_SCORE = 65
# ========== PATHS ==========
LOG_DIR = "logs"
DATA_DIR = "data"
