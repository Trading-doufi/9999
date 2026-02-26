cat > ~/trading-bot-pro/src/strategy_engine.py << 'EOF'
# src/strategy_engine.py
from kafka import KafkaConsumer
import json
import threading
import time
import redis
import numpy as np
from datetime import datetime
import logging

from config.settings import KAFKA_BOOTSTRAP_SERVERS, REDIS_HOST, REDIS_PORT, SYMBOLS, MIN_SCORE
from src.database import SignalDatabase
from src.logger import get_logger

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
trading_logger = get_logger()

class StrategyEngine:
    def __init__(self):
        self.consumer = KafkaConsumer(
            'depth', 'trades', 'liquidations',
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            auto_offset_reset='latest',
            enable_auto_commit=True,
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.db = SignalDatabase()
        self.price_history = {}
        self.liquidation_history = []
        self.symbols = SYMBOLS
        self.min_score = MIN_SCORE
        self.last_signal_time = {}
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.volume_threshold = 1.5
        self.start_analysis_thread()
        
    def start(self):
        trading_logger.main_logger.info("🚀 Strategy Engine started")
        for msg in self.consumer:
            try:
                if msg.topic == 'trades':
                    self.process_trade(msg.value)
                elif msg.topic == 'liquidations':
                    self.process_liquidation(msg.value)
            except Exception as e:
                trading_logger.log_error('strategy_engine.start', e)
    
    def process_trade(self, data):
        try:
            if 'data' in data and len(data['data']) > 0:
                for trade in data['data']:
                    symbol = trade['s']
                    price = float(trade['p'])
                    volume = float(trade['v'])
                    side = trade['S']
                    
                    if symbol not in self.price_history:
                        self.price_history[symbol] = []
                    self.price_history[symbol].append({
                        'price': price, 'volume': volume, 'side': side, 'time': trade['T']
                    })
                    if len(self.price_history[symbol]) > 100:
                        self.price_history[symbol] = self.price_history[symbol][-100:]
                    
                    self.redis.set(f"last_price:{symbol}", price)
        except Exception as e:
            trading_logger.log_error('strategy_engine.process_trade', e)
    
    def process_liquidation(self, data):
        try:
            if 'data' in data:
                for liq in data['data']:
                    self.liquidation_history.append(liq)
                    trading_logger.main_logger.info(f"💥 LIQUIDATION: {liq['s']} - {liq['side']}")
                    self.redis.set("latest_liquidation", json.dumps(liq))
                    if len(self.liquidation_history) > 50:
                        self.liquidation_history = self.liquidation_history[-50:]
        except Exception as e:
            trading_logger.log_error('strategy_engine.process_liquidation', e)
    
    def calculate_rsi(self, prices):
        if len(prices) < 14:
            return 50
        
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            if diff > 0:
                gains.append(diff)
            else:
                losses.append(abs(diff))
        
        avg_gain = np.mean(gains[-14:]) if gains else 0
        avg_loss = np.mean(losses[-14:]) if losses else 1
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def determine_direction(self, symbol):
        try:
            history = self.price_history.get(symbol, [])
            if len(history) < 21:
                return "LONG 🟢"
            
            prices = [p['price'] for p in history[-21:]]
            ema9 = sum(prices[-9:]) / 9
            ema21 = sum(prices) / 21
            
            if ema9 > ema21:
                return "LONG 🟢"
            else:
                return "SHORT 🔴"
        except:
            return "LONG 🟢"
    
    def calculate_trade_levels(self, symbol, price, score, direction):
        # ========== تعديل النسب هنا ==========
        risk_percent = 0.05  # 5% وقف خسارة (غيّر إلى 0.10 لـ 10%، 0.20 لـ 20%)
        
        if score >= 85:
            reward_ratios = [2, 4, 6]   # 10%، 20%، 30% ربح
        elif score >= 75:
            reward_ratios = [1.5, 3, 5] # 7.5%، 15%، 25% ربح
        else:
            reward_ratios = [1, 2, 3]   # 5%، 10%، 15% ربح
        # =====================================
        
        if direction == "LONG 🟢":
            entry = price
            stop_loss = price * (1 - risk_percent)
            
            tp1 = entry * (1 + risk_percent * reward_ratios[0])
            tp2 = entry * (1 + risk_percent * reward_ratios[1])
            tp3 = entry * (1 + risk_percent * reward_ratios[2])
        else:  # SHORT
            entry = price
            stop_loss = price * (1 + risk_percent)
            
            tp1 = entry * (1 - risk_percent * reward_ratios[0])
            tp2 = entry * (1 - risk_percent * reward_ratios[1])
            tp3 = entry * (1 - risk_percent * reward_ratios[2])
        
        profit_tp1 = abs((tp1 - entry) / entry) * 100
        profit_tp2 = abs((tp2 - entry) / entry) * 100
        profit_tp3 = abs((tp3 - entry) / entry) * 100
        
        return {
            'entry': round(entry, 2),
            'stop_loss': round(stop_loss, 2),
            'tp1': round(tp1, 2),
            'tp2': round(tp2, 2),
            'tp3': round(tp3, 2),
            'profit_tp1': round(profit_tp1, 2),
            'profit_tp2': round(profit_tp2, 2),
            'profit_tp3': round(profit_tp3, 2)
        }
    
    def calculate_score(self, symbol):
        try:
            history = self.price_history.get(symbol, [])
            if len(history) < 20:
                return 50, 50, False
            
            prices = [p['price'] for p in history[-20:]]
            volumes = [p['volume'] for p in history[-20:]]
            rsi = self.calculate_rsi(prices)
            
            if rsi < 5 or rsi > 95:
                rsi = 50
            
            score = 50
            
            if rsi < self.rsi_oversold:
                rsi_factor = (self.rsi_oversold - rsi) / self.rsi_oversold
                score += 20 * (1 + rsi_factor)
            elif rsi > self.rsi_overbought:
                rsi_factor = (rsi - self.rsi_overbought) / (100 - self.rsi_overbought)
                score -= 20 * (1 + rsi_factor)
            
            if len(prices) >= 21:
                ema9 = sum(prices[-9:]) / 9
                ema21 = sum(prices[-21:]) / 21
                ema_diff = (ema9 - ema21) / ema21
                
                if ema9 > ema21:
                    score += 15 * (1 + min(abs(ema_diff) * 10, 1))
                else:
                    score -= 15 * (1 + min(abs(ema_diff) * 10, 1))
            
            avg_volume = sum(volumes) / len(volumes) if volumes else 1
            last_volume = volumes[-1] if volumes else 0
            if last_volume > avg_volume * self.volume_threshold:
                if score > 50:
                    score += 10
                else:
                    score -= 10
            
            last_price = prices[-1]
            recent = [l for l in self.liquidation_history 
                     if l.get('s') == symbol and 
                     abs(float(l.get('price', 0)) - last_price) / last_price < 0.03]
            liquidation_detected = len(recent) > 0
            if liquidation_detected:
                score += 25
            
            return max(0, min(100, score)), rsi, liquidation_detected
            
        except Exception as e:
            trading_logger.log_error('strategy_engine.calculate_score', e, {'symbol': symbol})
            return 50, 50, False
    
    def analyze_signals(self):
        while True:
            try:
                for symbol in self.symbols:
                    score, rsi, liquidation_detected = self.calculate_score(symbol)
                    
                    if score >= self.min_score:
                        if symbol not in self.price_history or len(self.price_history[symbol]) == 0:
                            continue
                        price = self.price_history[symbol][-1]['price']
                        direction = self.determine_direction(symbol)
                        
                        current_time = time.time()
                        last_time = self.last_signal_time.get(symbol, 0)
                        if current_time - last_time < 300:
                            continue
                        
                        levels = self.calculate_trade_levels(symbol, price, score, direction)
                        
                        if score >= 85:
                            leverage = 10
                        elif score >= 75:
                            leverage = 5
                        else:
                            leverage = 3
                        
                        signal = {
                            'symbol': symbol,
                            'score': score,
                            'rsi': round(rsi, 1),
                            'price': price,
                            'direction': direction,
                            'entry': levels['entry'],
                            'stop_loss': levels['stop_loss'],
                            'tp1': levels['tp1'],
                            'tp2': levels['tp2'],
                            'tp3': levels['tp3'],
                            'profit_tp1': levels['profit_tp1'],
                            'profit_tp2': levels['profit_tp2'],
                            'profit_tp3': levels['profit_tp3'],
                            'liquidation_detected': liquidation_detected,
                            'leverage': leverage,
                            'time': datetime.now().isoformat(),
                            'reason': f"Score {score}% - {'Liquidation' if liquidation_detected else 'Technical'}"
                        }
                        
                        self.redis.set(f"signal:{symbol}", json.dumps(signal))
                        self.redis.publish('signals', json.dumps(signal))
                        
                        signal_id = self.db.save_signal(signal)
                        trading_logger.log_signal(signal)
                        
                        self.last_signal_time[symbol] = current_time
                        
                        logger.info(f"✅ PROFESSIONAL SIGNAL: {symbol} - {direction} - Score: {score}")
                        
            except Exception as e:
                trading_logger.log_error('strategy_engine.analyze_signals', e)
            
            time.sleep(30)
    
    def start_analysis_thread(self):
        thread = threading.Thread(target=self.analyze_signals, daemon=True)
        thread.start()
EOF
