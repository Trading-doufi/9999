import redis
import json
import time
import threading
import requests
import logging

from config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, REDIS_HOST, REDIS_PORT
from src.logger import get_logger

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
trading_logger = get_logger()

class ProfessionalTelegramBot:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
    def send_message(self, text):
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {'chat_id': self.chat_id, 'text': text, 'parse_mode': 'Markdown'}
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                trading_logger.main_logger.info("✅ Message sent to Telegram")
            else:
                trading_logger.log_error('telegram_bot.send_message', response.text)
        except Exception as e:
            trading_logger.log_error('telegram_bot.send_message', e)
    
    def format_signal(self, signal):
        symbol = signal['symbol']
        score = signal['score']
        direction = signal['direction']
        entry = signal['entry']
        stop_loss = signal['stop_loss']
        tp1 = signal['tp1']
        tp2 = signal['tp2']
        tp3 = signal['tp3']
        profit_tp1 = signal['profit_tp1']
        profit_tp2 = signal['profit_tp2']
        profit_tp3 = signal['profit_tp3']
        leverage = signal['leverage']
        liquidation = signal.get('liquidation_detected', False)
        reason = signal.get('reason', 'Technical setup')
        rsi = signal.get('rsi', 50)
        
        if score >= 85:
            emoji = "🚀🔥"
        elif score >= 75:
            emoji = "📈"
        else:
            emoji = "⚡"
        
        signal_text = f"""
{emoji} *إشارة تداول احترافية* {emoji}

📊 *{symbol}*

{direction}
💰 *الدخول:* `{entry}`
🛑 *وقف الخسارة:* `{stop_loss}`

🎯 *أهداف الربح:*
├ TP1: `{tp1}` (+{profit_tp1}%)
├ TP2: `{tp2}` (+{profit_tp2}%)
└ TP3: `{tp3}` (+{profit_tp3}%)

⚡ *الرافعة المقترحة:* `x{leverage}`
⭐ *الثقة:* `{score}%`

📋 *التحليل:*
• {reason}
• RSI: `{rsi}`
• التصفيات: {'✅' if liquidation else '❌'}

#{symbol} #Signal
"""
        return signal_text
    
    def check_signals(self):
        last_signals = {}
        while True:
            try:
                keys = self.redis.keys("signal:*")
                for key in keys:
                    symbol = key.split(":")[1]
                    data = self.redis.get(key)
                    if data:
                        signal = json.loads(data)
                        if last_signals.get(symbol) != signal.get('time'):
                            msg = self.format_signal(signal)
                            if msg:
                                self.send_message(msg)
                                last_signals[symbol] = signal.get('time')
                                logger.info(f"✅ Professional signal sent for {symbol}")
            except Exception as e:
                trading_logger.log_error('telegram_bot.check_signals', e)
            time.sleep(5)
    
    def start(self):
        trading_logger.main_logger.info("🚀 Professional Telegram Bot started")
        self.send_message("🤖 *بوت التداول الاحترافي*\n✅ متصل بـ Redis و Kafka\n⏱️ في انتظار إشارات قوية...")
        threading.Thread(target=self.check_signals, daemon=True).start()
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            trading_logger.main_logger.info("🛑 Stopping bot...")

