# src/bybit_ingestor.py
import json
import threading
import time
import logging
from websocket import WebSocketApp
from kafka import KafkaProducer
import redis

from config.settings import BYBIT_WS_URL, REDIS_HOST, REDIS_PORT, KAFKA_BOOTSTRAP_SERVERS, SYMBOLS
from src.logger import get_logger

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
trading_logger = get_logger()

class BybitWebSocketIngestor:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.ws_connections = {}
        
    def start(self):
        # قم بإنشاء المواضيع بناءً على SYMBOLS من الإعدادات
        depth_topics = [f"orderbook.50.{symbol}" for symbol in SYMBOLS]
        trade_topics = [f"publicTrade.{symbol}" for symbol in SYMBOLS]
        
        topics = depth_topics + trade_topics + ['all.liquidations']
        
        # تقسيم المواضيع إلى مجموعات لأن WebSocket قد لا يقبل 100+ اشتراك دفعة واحدة
        chunk_size = 20
        for i in range(0, len(topics), chunk_size):
            chunk = topics[i:i+chunk_size]
            self.connect_websocket(f'bybit_{i//chunk_size}', BYBIT_WS_URL, chunk)
            time.sleep(1)  # انتظر قليلاً بين الاتصالات
        
        trading_logger.main_logger.info(f"✅ Bybit WebSocket Ingestor started with {len(SYMBOLS)} symbols")
        
    def connect_websocket(self, name, url, topics):
        def on_message(ws, message):
            self.handle_message(name, message)
            
        def on_error(ws, error):
            trading_logger.log_error('bybit_ingestor', error)
            
        def on_close(ws, close_status_code, close_msg):
            trading_logger.main_logger.warning(f"⚠️ WebSocket {name} closed. Reconnecting...")
            time.sleep(5)
            self.connect_websocket(name, url, topics)
            
        def on_open(ws):
            for topic in topics:
                subscribe_msg = {"op": "subscribe", "args": [topic]}
                ws.send(json.dumps(subscribe_msg))
                trading_logger.main_logger.info(f"✅ Subscribed to {topic}")
        
        def run_websocket():
            ws = WebSocketApp(url, on_open=on_open, on_message=on_message,
                             on_error=on_error, on_close=on_close)
            self.ws_connections[name] = ws
            ws.run_forever()
        
        thread = threading.Thread(target=run_websocket, daemon=True)
        thread.start()
        
    def handle_message(self, source, message):
        try:
            data = json.loads(message)
            
            if 'topic' in data:
                topic = data['topic']
                if 'orderbook' in topic:
                    symbol = topic.split('.')[-1]
                    self.redis.set(f"orderbook:{symbol}", json.dumps(data))
                    self.redis.expire(f"orderbook:{symbol}", 2)
                    self.producer.send('depth', data)
                    
                elif 'publicTrade' in topic:
                    symbol = topic.split('.')[-1]
                    if 'data' in data and len(data['data']) > 0:
                        self.redis.set(f"last_trade:{symbol}", json.dumps(data['data'][-1]))
                        self.producer.send('trades', data)
                        
                elif 'liquidation' in topic:
                    self.redis.set("last_liquidation", json.dumps(data))
                    self.producer.send('liquidations', data)
                    trading_logger.main_logger.info(f"💥 Liquidation detected")
                    
        except Exception as e:
            trading_logger.log_error('bybit_ingestor.handle_message', e)
    
    def get_current_price(self, symbol):
        try:
            last_trade = self.redis.get(f"last_trade:{symbol}")
            if last_trade:
                data = json.loads(last_trade)
                return float(data['p'])
        except: pass
        return None



