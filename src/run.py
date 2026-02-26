import threading
import time
import logging
import sys
import os
import atexit

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from src.bybit_ingestor import BybitWebSocketIngestor
from src.strategy_engine import StrategyEngine
from src.telegram_bot import ProfessionalTelegramBot
from src.performance_reporter import PerformanceReporter
from src.database import SignalDatabase
from src.logger import get_logger

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
trading_logger = get_logger()
db = SignalDatabase()

def cleanup():
    trading_logger.main_logger.info("🛑 Cleaning up...")
    db.close()

atexit.register(cleanup)

def check_services():
    import socket
    import redis
    from pymongo import MongoClient
    
    kafka_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    kafka_up = kafka_sock.connect_ex(('localhost', 9092)) == 0
    kafka_sock.close()
    
    redis_up = False
    try:
        r = redis.Redis(host='localhost', port=6379)
        r.ping()
        redis_up = True
    except:
        pass
    
    mongo_up = False
    try:
        client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        mongo_up = True
    except:
        pass
    
    if not kafka_up:
        trading_logger.log_error('run.check_services', 'Kafka is not running')
        return False
    if not redis_up:
        trading_logger.log_error('run.check_services', 'Redis is not running')
        return False
    if not mongo_up:
        trading_logger.log_error('run.check_services', 'MongoDB is not running')
        return False
    
    trading_logger.main_logger.info("✅ Kafka, Redis and MongoDB are running")
    return True

def main():
    trading_logger.main_logger.info("🚀 Starting all services...")
    
    if not check_services():
        trading_logger.main_logger.error("❌ Please start Kafka, Redis and MongoDB first")
        return
    
    ingestor = BybitWebSocketIngestor()
    ingestor.start()
    trading_logger.main_logger.info("✅ Bybit Ingestor started")
    
    time.sleep(2)
    
    engine = StrategyEngine()
    threading.Thread(target=engine.start, daemon=True).start()
    trading_logger.main_logger.info("✅ Strategy Engine started")
    
    time.sleep(2)
    
    bot = ProfessionalTelegramBot()
    threading.Thread(target=bot.start, daemon=True).start()
    trading_logger.main_logger.info("✅ Professional Telegram Bot started")
    
    time.sleep(2)
    
    reporter = PerformanceReporter()
    threading.Thread(target=reporter.start, daemon=True).start()
    trading_logger.main_logger.info("✅ Performance Reporter started")
    
    trading_logger.main_logger.info("✅ All services started. Press Ctrl+C to stop.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        trading_logger.main_logger.info("🛑 Stopping all services...")

if __name__ == "__main__":
    main()
EOF

