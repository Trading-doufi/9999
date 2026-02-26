# src/logger.py
import logging
import logging.handlers
import os
from datetime import datetime
import json

class TradingLogger:
    def __init__(self, log_dir="logs"):
        self.log_dir = log_dir
        self.setup_logging()
    
    def setup_logging(self):
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Main Logger
        main_handler = logging.handlers.RotatingFileHandler(
            f"{self.log_dir}/trading_bot.log",
            maxBytes=10*1024*1024,
            backupCount=5
        )
        main_handler.setFormatter(formatter)
        
        self.main_logger = logging.getLogger('trading_bot')
        self.main_logger.setLevel(logging.INFO)
        self.main_logger.addHandler(main_handler)
        
        # Signals Logger
        signals_handler = logging.handlers.RotatingFileHandler(
            f"{self.log_dir}/signals.log",
            maxBytes=10*1024*1024,
            backupCount=5
        )
        signals_handler.setFormatter(formatter)
        
        self.signals_logger = logging.getLogger('signals')
        self.signals_logger.setLevel(logging.INFO)
        self.signals_logger.addHandler(signals_handler)
        
        # Errors Logger
        errors_handler = logging.handlers.RotatingFileHandler(
            f"{self.log_dir}/errors.log",
            maxBytes=10*1024*1024,
            backupCount=5
        )
        errors_handler.setFormatter(formatter)
        
        self.errors_logger = logging.getLogger('errors')
        self.errors_logger.setLevel(logging.ERROR)
        self.errors_logger.addHandler(errors_handler)
        
        # Performance Logger
        perf_handler = logging.handlers.RotatingFileHandler(
            f"{self.log_dir}/performance.log",
            maxBytes=10*1024*1024,
            backupCount=5
        )
        perf_handler.setFormatter(formatter)
        
        self.perf_logger = logging.getLogger('performance')
        self.perf_logger.setLevel(logging.INFO)
        self.perf_logger.addHandler(perf_handler)
        
        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.main_logger.addHandler(console_handler)
        
        print(f"✅ Logging system initialized in {self.log_dir}")
    
    def log_signal(self, signal):
        signal_info = {
            'timestamp': signal.get('time'),
            'symbol': signal.get('symbol'),
            'score': signal.get('score'),
            'direction': signal.get('direction'),
            'entry': signal.get('entry'),
            'stop_loss': signal.get('stop_loss'),
            'tp1': signal.get('tp1'),
            'tp2': signal.get('tp2'),
            'tp3': signal.get('tp3'),
            'leverage': signal.get('leverage'),
            'liquidation': signal.get('liquidation_detected', False),
            'reason': signal.get('reason')
        }
        self.signals_logger.info(json.dumps(signal_info))
        self.main_logger.info(f"📊 SIGNAL: {signal['symbol']} - {signal['direction']} - Score: {signal['score']}")
    
    def log_trade_result(self, signal_id, pnl, result_type):
        result_info = {
            'signal_id': signal_id,
            'pnl': pnl,
            'result': result_type,
            'timestamp': datetime.now().isoformat()
        }
        self.perf_logger.info(json.dumps(result_info))
        self.main_logger.info(f"💰 TRADE CLOSED: ID {signal_id} - PnL: {pnl} - {result_type}")
    
    def log_error(self, module, error, details=None):
        error_info = {
            'module': module,
            'error': str(error),
            'details': details,
            'timestamp': datetime.now().isoformat()
        }
        self.errors_logger.error(json.dumps(error_info))
        self.main_logger.error(f"❌ ERROR in {module}: {error}")
    
    def log_performance(self, stats):
        self.perf_logger.info(f"📈 PERFORMANCE: {json.dumps(stats)}")

logger = TradingLogger()

def get_logger():
    return logger



