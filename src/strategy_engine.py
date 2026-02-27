# src/strategy_engine.py
from kafka import KafkaConsumer
import json
import threading
import time
import redis
import numpy as np
from datetime import datetime, timedelta
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
        self.price_history_4h = {}
        self.liquidation_history = []
        self.symbols = SYMBOLS
        self.min_score = MIN_SCORE
        self.last_signal_time = {}
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.volume_threshold = 1.5
        self.last_4h_update = {}
        
        # تنظيف الذاكرة عند بدء التشغيل
        self.price_history = {}
        self.price_history_4h = {}
        self.liquidation_history = []
        self.last_4h_update = {}
        self.last_signal_time = {}
        trading_logger.main_logger.info("🧹 Cleaned internal memory on startup")
        
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
                    trade_time = int(trade['T']) / 1000

                    if symbol not in self.price_history:
                        self.price_history[symbol] = []
                    self.price_history[symbol].append({
                        'price': price, 'volume': volume, 'side': side, 'time': trade_time
                    })
                    if len(self.price_history[symbol]) > 100:
                        self.price_history[symbol] = self.price_history[symbol][-100:]

                    self.update_4h_data(symbol, price, trade_time)
                    self.redis.set(f"last_price:{symbol}", price)
        except Exception as e:
            trading_logger.log_error('strategy_engine.process_trade', e)

    def update_4h_data(self, symbol, price, trade_time):
        try:
            period_4h = int(trade_time / (4 * 3600))
            last_period = self.last_4h_update.get(symbol, 0)
            
            if period_4h > last_period:
                if symbol not in self.price_history_4h:
                    self.price_history_4h[symbol] = []
                
                self.price_history_4h[symbol].append({
                    'price': price,
                    'time': trade_time,
                    'period': period_4h
                })
                
                if len(self.price_history_4h[symbol]) > 100:
                    self.price_history_4h[symbol] = self.price_history_4h[symbol][-100:]
                
                self.last_4h_update[symbol] = period_4h
                trading_logger.main_logger.info(f"📊 4H data updated for {symbol}: {price}")
        except Exception as e:
            trading_logger.log_error('strategy_engine.update_4h_data', e)

    def get_trend_from_4h(self, symbol):
        try:
            history_4h = self.price_history_4h.get(symbol, [])
            if len(history_4h) < 21:
                return "NEUTRAL", 50
            
            prices = [p['price'] for p in history_4h[-21:]]
            
            ema9 = np.mean(prices[-9:])
            ema21 = np.mean(prices)
            
            if ema9 > ema21:
                strength = min(100, 50 + ((ema9 - ema21) / ema21) * 500)
                return "LONG 🟢", round(strength, 1)
            else:
                strength = min(100, 50 + ((ema21 - ema9) / ema21) * 500)
                return "SHORT 🔴", round(strength, 1)
        except Exception as e:
            trading_logger.log_error('strategy_engine.get_trend_from_4h', e)
            return "NEUTRAL", 50

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
        if score >= 85:
            risk_percent = 0.05
            reward_ratios = [2, 4, 6]
        elif score >= 75:
            risk_percent = 0.05
            reward_ratios = [1.5, 3, 5]
        else:
            risk_percent = 0.04
            reward_ratios = [1.5, 2.5, 4]

        if direction == "LONG 🟢":
            entry = price
            stop_loss = price * (1 - risk_percent)
            tp1 = entry * (1 + risk_percent * reward_ratios[0])
            tp2 = entry * (1 + risk_percent * reward_ratios[1])
            tp3 = entry * (1 + risk_percent * reward_ratios[2])
        else:
            entry = price
            stop_loss = price * (1 + risk_percent)
            tp1 = entry * (1 - risk_percent * reward_ratios[0])
            tp2 = entry * (1 - risk_percent * reward_ratios[1])
            tp3 = entry * (1 - risk_percent * reward_ratios[2])

        profit_tp1 = abs((tp1 - entry) / entry) * 100
        profit_tp2 = abs((tp2 - entry) / entry) * 100
        profit_tp3 = abs((tp3 - entry) / entry) * 100

        if entry < 0.0001:
            precision = 6
        elif entry < 0.001:
            precision = 5
        elif entry < 0.01:
            precision = 4
        elif entry < 0.1:
            precision = 4
        elif entry < 1:
            precision = 4
        else:
            precision = 2

        return {
            'entry': round(entry, precision),
            'stop_loss': round(stop_loss, precision),
            'tp1': round(tp1, precision),
            'tp2': round(tp2, precision),
            'tp3': round(tp3, precision),
            'profit_tp1': round(profit_tp1, 1),
            'profit_tp2': round(profit_tp2, 1),
            'profit_tp3': round(profit_tp3, 1)
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
                        direction_15m = self.determine_direction(symbol)
                        trend_4h, trend_strength = self.get_trend_from_4h(symbol)
                        
                        adjusted_score = score
                        trend_match = False
                        
                        if trend_4h != "NEUTRAL":
                            if (direction_15m == "LONG 🟢" and trend_4h == "LONG 🟢") or \
                               (direction_15m == "SHORT 🔴" and trend_4h == "SHORT 🔴"):
                                adjusted_score = min(100, score + 10)
                                trend_match = True
                                trading_logger.main_logger.info(f"✅ {symbol}: Signal aligns with 4H trend ({trend_4h})")
                            else:
                                if score >= 85:
                                    adjusted_score = score - 5
                                elif score >= 75:
                                    adjusted_score = score - 10
                                else:
                                    adjusted_score = score - 15
                                    continue
                                trading_logger.main_logger.info(f"⚠️ {symbol}: Signal against 4H trend")

                        current_time = time.time()
                        last_time = self.last_signal_time.get(symbol, 0)
                        if current_time - last_time < 600:
                            continue

                        if adjusted_score >= self.min_score:
                            levels = self.calculate_trade_levels(symbol, price, adjusted_score, direction_15m)
                            if adjusted_score >= 85:
                                leverage = 10
                            elif adjusted_score >= 75:
                                leverage = 5
                            else:
                                leverage = 3

                            signal = {
                                'symbol': symbol,
                                'score': round(adjusted_score, 1),
                                'original_score': round(score, 1),
                                'trend_4h': trend_4h,
                                'trend_strength': trend_strength,
                                'trend_match': trend_match,
                                'rsi': round(rsi, 1),
                                'price': round(price, 4) if price < 1 else round(price, 2),
                                'direction': direction_15m,
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
                                'reason': f"Score {round(adjusted_score, 1)}% | 4H {trend_4h} ({trend_strength}%) | {'✅ Aligned' if trend_match else '⚠️ Against trend'}"
                            }

                            self.redis.set(f"signal:{symbol}", json.dumps(signal))
                            self.redis.publish('signals', json.dumps(signal))
                            signal_id = self.db.save_signal(signal)
                            trading_logger.log_signal(signal)
                            self.last_signal_time[symbol] = current_time
                            logger.info(f"✅ SIGNAL: {symbol} - {direction_15m} - Score: {round(adjusted_score, 1)} | 4H: {trend_4h} ({trend_strength}%)")

            except Exception as e:
                trading_logger.log_error('strategy_engine.analyze_signals', e)
            time.sleep(60)

    def start_analysis_thread(self):
        thread = threading.Thread(target=self.analyze_signals, daemon=True)
        thread.start()
