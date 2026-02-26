cat > ~/trading-bot-pro/src/performance_reporter.py << 'EOF'
# src/performance_reporter.py
import time
import schedule
import logging
from datetime import datetime

from config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from src.database import SignalDatabase
from src.telegram_bot import ProfessionalTelegramBot
from src.logger import get_logger

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
trading_logger = get_logger()

class PerformanceReporter:
    def __init__(self):
        self.db = SignalDatabase()
        self.bot = ProfessionalTelegramBot()
    
    def generate_daily_report(self):
        try:
            stats = self.db.get_statistics(days=1)
            best = self.db.get_best_symbols(3, days=1)
            
            report = f"""
📊 *تقرير الأداء اليومي*

📈 *آخر 24 ساعة:*
• إجمالي الإشارات: `{stats['total']}`
• صفقات رابحة: `{stats['winning']}`
• صفقات خاسرة: `{stats['losing']}`
• نسبة النجاح: `{stats['win_rate']}%`
• صافي الربح: `${stats['total_pnl']}`

🏆 *أفضل العملات اليوم:*
"""
            for s in best:
                report += f"• {s['symbol']}: {s['wins']}/{s['count']} ربح ⌀ {s['avg_pnl']}%\n"
            
            report += f"""
⚡ *إحصائيات:*
• متوسط الربح: `${stats['avg_win']}`
• متوسط الخسارة: `${stats['avg_loss']}`
• أفضل صفقة: `${stats['max_win']}`
• أسوأ صفقة: `${stats['max_loss']}`

⏱ *التقرير:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            self.bot.send_message(report)
            trading_logger.log_performance(stats)
            logger.info("✅ Daily report sent")
        except Exception as e:
            trading_logger.log_error('performance_reporter.daily', e)
    
    def generate_weekly_report(self):
        try:
            summary = self.db.get_performance_summary(days=7)
            stats = summary['statistics']
            best = summary['best_symbols']
            
            report = f"""
📊 *تقرير الأداء الأسبوعي*

📈 *آخر 7 أيام:*
• إجمالي الإشارات: `{stats['total']}`
• صفقات رابحة: `{stats['winning']}`
• صفقات خاسرة: `{stats['losing']}`
• نسبة النجاح: `{stats['win_rate']}%`
• صافي الربح: `${stats['total_pnl']}`

🏆 *أفضل العملات:*
"""
            for s in best:
                win_rate = (s['wins'] / s['count'] * 100) if s['count'] > 0 else 0
                report += f"• {s['symbol']}: {s['wins']}/{s['count']} ({win_rate:.0f}%) ربح ⌀ {s['avg_pnl']}%\n"
            
            report += f"""
⚡ *إحصائيات متقدمة:*
• Profit Factor: `{summary['profit_factor']}`

⏱ *التقرير:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            self.bot.send_message(report)
            logger.info("✅ Weekly report sent")
        except Exception as e:
            trading_logger.log_error('performance_reporter.weekly', e)
    
    def generate_monthly_report(self):
        try:
            summary = self.db.get_performance_summary(days=30)
            stats = summary['statistics']
            best = summary['best_symbols']
            
            report = f"""
📊 *تقرير الأداء الشهري*

📈 *آخر 30 يوم:*
• إجمالي الإشارات: `{stats['total']}`
• صفقات رابحة: `{stats['winning']}`
• صفقات خاسرة: `{stats['losing']}`
• نسبة النجاح: `{stats['win_rate']}%`
• صافي الربح: `${stats['total_pnl']}`

🏆 *أفضل العملات:*
"""
            for s in best:
                win_rate = (s['wins'] / s['count'] * 100) if s['count'] > 0 else 0
                report += f"• {s['symbol']}: {s['wins']}/{s['count']} ({win_rate:.0f}%) - إجمالي ${s['total_pnl']}\n"
            
            report += f"""
⚡ *إحصائيات متقدمة:*
• Profit Factor: `{summary['profit_factor']}`

⏱ *التقرير:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            self.bot.send_message(report)
            logger.info("✅ Monthly report sent")
        except Exception as e:
            trading_logger.log_error('performance_reporter.monthly', e)
    
    def start(self):
        schedule.every().day.at("00:00").do(self.generate_daily_report)
        schedule.every().monday.at("00:00").do(self.generate_weekly_report)
        schedule.every(30).days.at("00:00").do(self.generate_monthly_report)
        
        while True:
            schedule.run_pending()
            time.sleep(60)
EOF
