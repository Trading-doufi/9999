from pymongo import MongoClient
from datetime import datetime, timedelta
import logging
from config.settings import MONGODB_URI, MONGODB_DB

logger = logging.getLogger(__name__)

class SignalDatabase:
    def __init__(self):
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client[MONGODB_DB]
        self.signals = self.db.signals
        self.performance = self.db.performance
        
        self.signals.create_index("timestamp")
        self.signals.create_index("symbol")
        self.signals.create_index("score")
        self.signals.create_index("status")
        
        logger.info("✅ MongoDB connected")
    
    def save_signal(self, signal):
        signal['_id'] = f"{signal['symbol']}_{datetime.now().timestamp()}"
        signal['created_at'] = datetime.now()
        signal['status'] = 'pending'
        signal['result'] = 0
        signal['closed_at'] = None
        
        self.signals.insert_one(signal)
        logger.info(f"✅ Signal saved to MongoDB with ID: {signal['_id']}")
        return signal['_id']
    
    def update_signal_result(self, signal_id, pnl, status='closed'):
        self.signals.update_one(
            {'_id': signal_id},
            {'$set': {
                'status': status,
                'result': pnl,
                'closed_at': datetime.now()
            }}
        )
        logger.info(f"✅ Signal {signal_id} updated with PnL: {pnl}")
    
    def get_statistics(self, days=7):
        cutoff = datetime.now() - timedelta(days=days)
        
        pipeline = [
            {'$match': {'created_at': {'$gte': cutoff}}},
            {'$group': {
                '_id': None,
                'total': {'$sum': 1},
                'winning': {'$sum': {'$cond': [{'$gt': ['$result', 0]}, 1, 0]}},
                'losing': {'$sum': {'$cond': [{'$lt': ['$result', 0]}, 1, 0]}},
                'total_pnl': {'$sum': '$result'},
                'avg_win': {'$avg': {'$cond': [{'$gt': ['$result', 0]}, '$result', None]}},
                'avg_loss': {'$avg': {'$cond': [{'$lt': ['$result', 0]}, '$result', None]}},
                'max_win': {'$max': '$result'},
                'max_loss': {'$min': '$result'}
            }}
        ]
        
        result = list(self.signals.aggregate(pipeline))
        
        if not result:
            return {
                'total': 0, 'winning': 0, 'losing': 0, 'win_rate': 0,
                'total_pnl': 0, 'avg_win': 0, 'avg_loss': 0,
                'max_win': 0, 'max_loss': 0
            }
        
        stats = result[0]
        total = stats['total']
        winning = stats['winning'] or 0
        win_rate = (winning / total * 100) if total > 0 else 0
        
        return {
            'total': total,
            'winning': winning,
            'losing': stats['losing'] or 0,
            'win_rate': round(win_rate, 2),
            'total_pnl': round(stats['total_pnl'] or 0, 2),
            'avg_win': round(stats['avg_win'] or 0, 2),
            'avg_loss': round(stats['avg_loss'] or 0, 2),
            'max_win': round(stats['max_win'] or 0, 2),
            'max_loss': round(stats['max_loss'] or 0, 2)
        }
    
    def get_best_symbols(self, limit=3, days=30):
        cutoff = datetime.now() - timedelta(days=days)
        
        pipeline = [
            {'$match': {
                'created_at': {'$gte': cutoff},
                'result': {'$ne': 0}
            }},
            {'$group': {
                '_id': '$symbol',
                'count': {'$sum': 1},
                'wins': {'$sum': {'$cond': [{'$gt': ['$result', 0]}, 1, 0]}},
                'avg_pnl': {'$avg': '$result'},
                'total_pnl': {'$sum': '$result'}
            }},
            {'$sort': {'avg_pnl': -1}},
            {'$limit': limit}
        ]
        
        results = []
        for doc in self.signals.aggregate(pipeline):
            results.append({
                'symbol': doc['_id'],
                'count': doc['count'],
                'wins': doc['wins'],
                'avg_pnl': round(doc['avg_pnl'], 2),
                'total_pnl': round(doc['total_pnl'], 2)
            })
        
        return results
    
    def get_performance_summary(self, days=30):
        stats = self.get_statistics(days)
        best = self.get_best_symbols(5, days)
        
        profit_factor = abs(stats['avg_win'] / stats['avg_loss']) if stats['avg_loss'] != 0 else float('inf')
        
        return {
            'period': f"{days} days",
            'statistics': stats,
            'best_symbols': best,
            'profit_factor': round(profit_factor, 2),
            'total_signals': stats['total']
        }
    
    def close(self):
        self.client.close()



