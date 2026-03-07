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
        self.price_history_4h = {}
        self.liquidation_history = []
        self.symbols = SYMBOLS
        self.min_score = MIN_SCORE
        self.last_signal_time = {}
        self.sl_history = []
        self.active_directions = {}
        self.trading_paused_until = None
        self.last_4h_update = {}
        self.volume_threshold = 1.5
        # ── Breakout Confirmation ──────────────────────────────
        self.pending_signals      = {}      # symbol → {signal, confirm_price, direction, expires_at}
        self.CONFIRMATION_PCT     = 0.003   # 0.3% فوق entry (LONG) أو تحته (SHORT)
        self.CONFIRMATION_TIMEOUT = 300     # 5 دقايق انتظار max
        trading_logger.main_logger.info("🧹 Memory cleaned on startup")
        self.preload_all_symbols()
        self.start_analysis_thread()

    # ─────────────────────────────────────────────
    #  DATA INGESTION
    # ─────────────────────────────────────────────

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
            if 'data' in data and data['data']:
                for trade in data['data']:
                    symbol     = trade['s']
                    price      = float(trade['p'])
                    volume     = float(trade['v'])
                    side       = trade['S']
                    trade_time = int(trade['T']) / 1000
                    if symbol not in self.price_history:
                        self.price_history[symbol] = []
                    self.price_history[symbol].append({
                        'price': price, 'volume': volume,
                        'side': side, 'time': trade_time
                    })
                    if len(self.price_history[symbol]) > 300:
                        self.price_history[symbol] = self.price_history[symbol][-300:]
                    self.update_4h_data(symbol, price, trade_time)
                    self.redis.set(f"last_price:{symbol}", price)
        except Exception as e:
            trading_logger.log_error('strategy_engine.process_trade', e)

    def update_4h_data(self, symbol, price, trade_time):
        try:
            period_4h = int(trade_time / (4 * 3600))
            if period_4h > self.last_4h_update.get(symbol, 0):
                if symbol not in self.price_history_4h:
                    self.price_history_4h[symbol] = []
                self.price_history_4h[symbol].append({
                    'price': price, 'time': trade_time, 'period': period_4h
                })
                if len(self.price_history_4h[symbol]) > 100:
                    self.price_history_4h[symbol] = self.price_history_4h[symbol][-100:]
                self.last_4h_update[symbol] = period_4h
        except Exception as e:
            trading_logger.log_error('strategy_engine.update_4h_data', e)

    def process_liquidation(self, data):
        try:
            if 'data' in data:
                for liq in data['data']:
                    self.liquidation_history.append(liq)
                    self.redis.set("latest_liquidation", json.dumps(liq))
                    if len(self.liquidation_history) > 100:
                        self.liquidation_history = self.liquidation_history[-100:]
        except Exception as e:
            trading_logger.log_error('strategy_engine.process_liquidation', e)

    # ─────────────────────────────────────────────
    #  INDICATORS
    # ─────────────────────────────────────────────

    def calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100
        return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)

    def calculate_ema(self, prices, period):
        if len(prices) < period:
            return float(np.mean(prices))
        k = 2 / (period + 1)
        ema = float(np.mean(prices[:period]))
        for p in prices[period:]:
            ema = p * k + ema * (1 - k)
        return ema

    def calculate_macd(self, prices):
        if len(prices) < 35:
            return 0, 0, 0, "NEUTRAL"
        macd_vals = []
        for i in range(26, len(prices) + 1):
            e12 = self.calculate_ema(prices[:i], 12)
            e26 = self.calculate_ema(prices[:i], 26)
            macd_vals.append(e12 - e26)
        if len(macd_vals) < 9:
            return 0, 0, 0, "NEUTRAL"
        macd_line   = macd_vals[-1]
        signal_line = self.calculate_ema(macd_vals, 9)
        histogram   = macd_line - signal_line
        prev_sig    = self.calculate_ema(macd_vals[:-1], 9) if len(macd_vals) > 1 else signal_line
        prev_hist   = macd_vals[-2] - prev_sig if len(macd_vals) > 1 else histogram
        if prev_hist < 0 and histogram > 0:
            trend = "BULLISH_CROSS"
        elif prev_hist > 0 and histogram < 0:
            trend = "BEARISH_CROSS"
        elif macd_line > signal_line:
            trend = "BULLISH"
        elif macd_line < signal_line:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"
        return round(macd_line, 8), round(signal_line, 8), round(histogram, 8), trend

    def calculate_bollinger_bands(self, prices, period=20, std_dev=2):
        if len(prices) < period:
            return None, None, None, 50
        recent = prices[-period:]
        middle = float(np.mean(recent))
        std    = float(np.std(recent))
        upper  = middle + std_dev * std
        lower  = middle - std_dev * std
        bw     = upper - lower
        pct_b  = ((prices[-1] - lower) / bw * 100) if bw > 0 else 50
        return round(upper, 8), round(middle, 8), round(lower, 8), round(pct_b, 1)

    def calculate_support_resistance(self, prices, window=5):
        if len(prices) < window * 2 + 1:
            return None, None
        supports, resistances = [], []
        for i in range(window, len(prices) - window):
            left  = prices[i - window:i]
            right = prices[i + 1:i + window + 1]
            p     = prices[i]
            if p <= min(left) and p <= min(right):
                supports.append(p)
            if p >= max(left) and p >= max(right):
                resistances.append(p)
        cur   = prices[-1]
        below = [s for s in supports    if s < cur]
        above = [r for r in resistances if r > cur]
        return (max(below) if below else None), (min(above) if above else None)

    def analyze_market_structure(self, prices):
        if len(prices) < 15:
            return "NEUTRAL", False
        chunk = 5
        highs, lows = [], []
        for i in range(0, len(prices) - chunk, chunk):
            seg = prices[i:i + chunk]
            highs.append(max(seg))
            lows.append(min(seg))
        if len(highs) < 3:
            return "NEUTRAL", False
        hh       = highs[-1] > highs[-2] > highs[-3]
        hl       = lows[-1]  > lows[-2]  > lows[-3]
        lh       = highs[-1] < highs[-2] < highs[-3]
        ll       = lows[-1]  < lows[-2]  < lows[-3]
        bos_bull = prices[-1] > highs[-2]
        bos_bear = prices[-1] < lows[-2]
        bos      = bos_bull or bos_bear
        if hh and hl:       return "UPTREND 📈",      bos
        elif lh and ll:     return "DOWNTREND 📉",    bos
        elif bos_bull:      return "BOS BULLISH 🔼",  True
        elif bos_bear:      return "BOS BEARISH 🔽",  True
        return "RANGING ↔️", False

    def get_trend_from_4h(self, symbol):
        try:
            h = self.price_history_4h.get(symbol, [])
            if len(h) < 21:
                return "NEUTRAL", 50
            prices = [p['price'] for p in h[-50:]]
            ema9   = self.calculate_ema(prices, 9)
            ema21  = self.calculate_ema(prices, 21)
            if ema9 > ema21:
                return "LONG 🟢",  round(min(100, 50 + ((ema9  - ema21) / ema21) * 500), 1)
            else:
                return "SHORT 🔴", round(min(100, 50 + ((ema21 - ema9)  / ema21) * 500), 1)
        except Exception as e:
            trading_logger.log_error('strategy_engine.get_trend_from_4h', e)
            return "NEUTRAL", 50

    def determine_direction(self, prices):
        if len(prices) < 26:
            return "LONG 🟢"
        return "LONG 🟢" if self.calculate_ema(prices, 9) > self.calculate_ema(prices, 21) else "SHORT 🔴"

    # ─────────────────────────────────────────────
    #  SCORE
    # ─────────────────────────────────────────────

    def calculate_score(self, symbol):
        try:
            history = self.price_history.get(symbol, [])
            if len(history) < 50:
                return 0, 50, False, {}, "NEUTRAL", False

            prices  = [p['price']  for p in history[-150:]]
            volumes = [p['volume'] for p in history[-150:]]
            sides   = [p['side']   for p in history[-50:]]

            direction = self.determine_direction(prices)
            is_long   = direction == "LONG 🟢"
            score     = 50
            details   = {}

            # 1. RSI (±25)
            rsi = self.calculate_rsi(prices)
            details['rsi'] = round(rsi, 1)
            if is_long:
                if rsi < 30:    score += 25
                elif rsi < 40:  score += 15
                elif rsi < 50:  score += 5
                elif rsi > 75:  score -= 20
                elif rsi > 65:  score -= 10
            else:
                if rsi > 70:    score += 25
                elif rsi > 60:  score += 15
                elif rsi > 50:  score += 5
                elif rsi < 25:  score -= 20
                elif rsi < 35:  score -= 10

            # 2. EMA strength (±20)
            if len(prices) >= 26:
                ema9  = self.calculate_ema(prices, 9)
                ema21 = self.calculate_ema(prices, 21)
                diff  = abs((ema9 - ema21) / ema21)
                pts   = min(20, diff * 2000)
                score += pts if is_long == (ema9 > ema21) else -pts

            # 3. MACD (±25)
            _, _, histogram, macd_trend = self.calculate_macd(prices)
            details['macd_trend']     = macd_trend
            details['macd_histogram'] = round(histogram, 8)
            is_cross  = "CROSS" in macd_trend
            macd_bull = macd_trend in ("BULLISH", "BULLISH_CROSS")
            macd_bear = macd_trend in ("BEARISH", "BEARISH_CROSS")
            pts = 25 if is_cross else 15
            if is_long:
                score += pts if macd_bull else (-pts if macd_bear else 0)
            else:
                score += pts if macd_bear else (-pts if macd_bull else 0)

            # 4. Bollinger Bands (±15)
            bb_up, _, bb_dn, pct_b = self.calculate_bollinger_bands(prices)
            details['bb_percent_b'] = pct_b
            details['bb_upper']     = bb_up
            details['bb_lower']     = bb_dn
            if bb_up and bb_dn:
                cur = prices[-1]
                if is_long:
                    if cur < bb_dn:   score += 15
                    elif pct_b < 20:  score += 8
                    elif cur > bb_up: score -= 15
                    elif pct_b > 80:  score -= 8
                else:
                    if cur > bb_up:   score += 15
                    elif pct_b > 80:  score += 8
                    elif cur < bb_dn: score -= 15
                    elif pct_b < 20:  score -= 8

            # 5. Market Structure (±15)
            structure, bos = self.analyze_market_structure(prices)
            details['market_structure'] = structure
            details['bos_detected']     = bos
            if is_long:
                if "UPTREND"   in structure or "BOS BULLISH" in structure: score += 15
                elif "DOWNTREND" in structure or "BOS BEARISH" in structure: score -= 15
            else:
                if "DOWNTREND" in structure or "BOS BEARISH" in structure: score += 15
                elif "UPTREND"   in structure or "BOS BULLISH" in structure: score -= 15

            # 6. Volume (+10)
            avg_vol   = float(np.mean(volumes)) if volumes else 1
            last_vol  = volumes[-1] if volumes else 0
            vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1
            details['volume_ratio'] = round(vol_ratio, 2)
            if vol_ratio > self.volume_threshold:
                score += min(10, (vol_ratio - 1) * 4)

            # 7. Buy/Sell pressure (±8)
            if len(sides) >= 10:
                buy_pct = sides[-20:].count('Buy') / min(20, len(sides[-20:]))
                details['buy_pressure'] = round(buy_pct * 100, 1)
                score += (buy_pct - 0.5) * 16 if is_long else -(buy_pct - 0.5) * 16
            else:
                details['buy_pressure'] = 50

            # 8. Liquidation (±15)
            last_price   = prices[-1]
            recent_liqs  = [
                l for l in self.liquidation_history
                if l.get('s') == symbol and
                abs(float(l.get('price', 0)) - last_price) / last_price < 0.03
            ]
            liq_detected = bool(recent_liqs)
            details['liquidation_detected'] = liq_detected
            if liq_detected:
                liq_side = recent_liqs[-1].get('side', '')
                if (liq_side == 'Sell' and is_long) or (liq_side == 'Buy' and not is_long):
                    score += 15
                else:
                    score -= 10

            return max(0, min(100, score)), rsi, liq_detected, details, structure, bos

        except Exception as e:
            trading_logger.log_error('strategy_engine.calculate_score', e, {'symbol': symbol})
            return 0, 50, False, {}, "NEUTRAL", False

    # ─────────────────────────────────────────────
    #  QUALITY GATE
    # ─────────────────────────────────────────────

    def is_valid_signal(self, direction, rsi, macd_trend, structure, score):
        is_long        = direction == "LONG 🟢"
        confirmations  = 0
        hard_blocks    = 0

        if is_long and rsi < 50:     confirmations += 1
        elif not is_long and rsi > 50: confirmations += 1
        if is_long and rsi > 80:     hard_blocks += 1
        elif not is_long and rsi < 20: hard_blocks += 1

        if is_long and macd_trend in ("BULLISH", "BULLISH_CROSS"):     confirmations += 1
        elif not is_long and macd_trend in ("BEARISH", "BEARISH_CROSS"): confirmations += 1

        if is_long and ("UPTREND" in structure or "BOS BULLISH" in structure):      confirmations += 1
        elif not is_long and ("DOWNTREND" in structure or "BOS BEARISH" in structure): confirmations += 1

        if hard_blocks >= 1:
            return False
        if is_long and rsi > 65 and macd_trend != "BULLISH_CROSS":
            return False
        if not is_long and rsi < 35 and macd_trend != "BEARISH_CROSS":
            return False

        return confirmations >= (1 if score >= 82 else 2)

    # ─────────────────────────────────────────────
    #  BTC CORRELATION
    # ─────────────────────────────────────────────

    def get_btc_correlation(self, symbol):
        try:
            btc_prices = list(self.price_history.get("BTCUSDT", []))
            sym_prices = list(self.price_history.get(symbol, []))
            if len(btc_prices) < 20 or len(sym_prices) < 20:
                return 0.7
            n       = min(len(btc_prices), len(sym_prices), 20)
            btc     = np.array([p['price'] for p in btc_prices[-n:]])
            sym     = np.array([p['price'] for p in sym_prices[-n:]])
            btc_ret = np.diff(btc) / btc[:-1]
            sym_ret = np.diff(sym) / sym[:-1]
            if np.std(btc_ret) == 0 or np.std(sym_ret) == 0:
                return 0.7
            corr = float(np.corrcoef(btc_ret, sym_ret)[0, 1])
            return corr if not np.isnan(corr) else 0.7
        except:
            return 0.7

    def check_correlation_lock(self, symbol, direction):
        CORRELATION_GROUPS = [
            {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT"},
            {"ATOMUSDT", "DOTUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT"},
            {"DYDXUSDT", "UNIUSDT", "AAVEUSDT", "COMPUSDT", "CRVUSDT", "SNXUSDT"},
            {"XLMUSDT", "ALGOUSDT", "VETUSDT", "XRPUSDT"},
            {"SANDUSDT", "MANAUSDT", "AXSUSDT", "APEUSDT", "GALAUSDT"},
            {"LINKUSDT", "GRTUSDT", "FILUSDT", "ICPUSDT"},
        ]
        symbol_group = None
        for group in CORRELATION_GROUPS:
            if symbol in group:
                symbol_group = group
                break
        if not symbol_group:
            return True, "OK"
        for active_sym, active_dir in self.active_directions.items():
            if active_sym == symbol:
                continue
            if active_sym in symbol_group:
                if "LONG"  in direction and "SHORT" in active_dir:
                    return False, f"Correlation block — {active_sym} already SHORT in same group"
                if "SHORT" in direction and "LONG"  in active_dir:
                    return False, f"Correlation block — {active_sym} already LONG in same group"
        return True, "OK"

    # ─────────────────────────────────────────────
    #  SL GUARD
    # ─────────────────────────────────────────────

    def check_sl_guard(self):
        now = time.time()
        self.sl_history = [t for t in self.sl_history if now - t < 3600]
        if self.trading_paused_until and now < self.trading_paused_until:
            remaining = int((self.trading_paused_until - now) / 60)
            return False, f"Trading paused — {remaining} min remaining"
        else:
            self.trading_paused_until = None
        if len(self.sl_history) >= 3:
            self.trading_paused_until = now + 5400
            return False, "3 SL in 1h — paused 90 min"
        return True, "OK"

    def record_sl_hit(self):
        self.sl_history.append(time.time())
        recent = len(self.sl_history)
        logger.info(f"📉 SL recorded | Total in 1h: {recent}/3")
        if recent >= 3:
            logger.warning("🛑 3 SL hit — trading will pause 90 min")

    # ─────────────────────────────────────────────
    #  MARKET REGIME
    # ─────────────────────────────────────────────

    def detect_market_regime(self, prices):
        if len(prices) < 50:
            return "UNKNOWN", "Not enough data"
        closes = np.array(prices)

        # ATR
        diffs      = np.abs(closes[1:] - closes[:-1])
        atr_cur    = float(np.mean(diffs[-14:]))
        atr_normal = float(np.mean(diffs[-28:-14]))
        if atr_normal > 0 and atr_cur > atr_normal * 2.0:
            return "CHAOTIC", f"ATR spike x{atr_cur/atr_normal:.1f}"

        # ADX
        plus_dm, minus_dm, tr_list = [], [], []
        for i in range(1, len(closes)):
            up   = closes[i] - closes[i-1]
            down = closes[i-1] - closes[i]
            plus_dm.append(max(up, 0))
            minus_dm.append(max(down, 0))
            tr_list.append(abs(closes[i] - closes[i-1]))
        plus_di  = float(np.mean(plus_dm[-14:]))
        minus_di = float(np.mean(minus_dm[-14:]))
        tr       = float(np.mean(tr_list[-14:]))
        adx      = abs(plus_di - minus_di) / tr * 100 if tr != 0 else 20

        # Whipsaw
        moves = [1 if closes[i] > closes[i-1] else -1 for i in range(-6, 0)]
        flips = sum(1 for i in range(1, len(moves)) if moves[i] != moves[i-1])
        if flips >= 4:
            return "WHIPSAW", f"{flips} direction flips"

        if adx > 25:   return "TRENDING",   f"ADX={adx:.0f}"
        elif adx < 18: return "RANGING",     f"ADX={adx:.0f}"
        else:          return "WEAK_TREND",  f"ADX={adx:.0f}"

    # ─────────────────────────────────────────────
    #  TRADE LEVELS
    # ─────────────────────────────────────────────

    def calculate_atr(self, prices, period=14):
        if len(prices) < period + 1:
            return 0.02
        ranges = [abs(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        return float(np.mean(ranges[-period:]))

    def calculate_trade_levels(self, symbol, price, score, direction):
        history = self.price_history.get(symbol, [])
        prices  = [p['price'] for p in history[-150:]] if len(history) >= 20 else []
        is_long = direction == "LONG 🟢"

        atr = self.calculate_atr(prices) if len(prices) >= 15 else 0.02
        if price > 1000:   min_sl = 0.008
        elif price > 100:  min_sl = 0.010
        elif price > 1:    min_sl = 0.015
        else:              min_sl = 0.020
        sl_pct = max(min_sl, min(0.05, atr * 1.5))

        if score >= 85:
            leverage = 10
            rr = [3.0, 6.0, 10.0]
        elif score >= 75:
            leverage = 7
            rr = [2.5, 5.0, 8.0]
        else:
            leverage = 5
            rr = [2.0, 4.0, 6.0]

        support, resistance = self.calculate_support_resistance(prices) if prices else (None, None)
        entry = price

        if is_long:
            if support and 0 < (entry - support) / entry <= sl_pct * 1.5:
                stop_loss = min(support * 0.998, entry * (1 - min_sl))
            else:
                stop_loss = entry * (1 - sl_pct)
            risk = entry - stop_loss
            tp1  = entry + risk * rr[0]
            tp2  = entry + risk * rr[1]
            tp3  = entry + risk * rr[2]
            if resistance and entry * 1.005 < resistance < tp2:
                tp1 = max(tp1, resistance * 0.997)
            tp1 = max(tp1, entry * (1 + sl_pct * rr[0]))
            tp2 = max(tp2, tp1 * 1.01)
            tp3 = max(tp3, tp2 * 1.01)
        else:
            if resistance and 0 < (resistance - entry) / entry <= sl_pct * 1.5:
                stop_loss = max(resistance * 1.002, entry * (1 + min_sl))
            else:
                stop_loss = entry * (1 + sl_pct)
            risk = stop_loss - entry
            tp1  = entry - risk * rr[0]
            tp2  = entry - risk * rr[1]
            tp3  = entry - risk * rr[2]
            if support and tp2 < support < entry * 0.995:
                tp1 = min(tp1, support * 1.003)
            tp1 = min(tp1, entry * (1 - sl_pct * rr[0]))
            tp2 = min(tp2, tp1 * 0.99)
            tp3 = min(tp3, tp2 * 0.99)

        prec       = 6 if entry < 0.001 else 5 if entry < 0.01 else 4 if entry < 1 else 4 if entry < 10 else 2
        actual_risk = abs(entry - stop_loss) / entry * 100
        p1 = abs(tp1 - entry) / entry * 100
        p2 = abs(tp2 - entry) / entry * 100
        p3 = abs(tp3 - entry) / entry * 100

        return {
            'entry':      round(entry,     prec),
            'stop_loss':  round(stop_loss, prec),
            'tp1':        round(tp1,       prec),
            'tp2':        round(tp2,       prec),
            'tp3':        round(tp3,       prec),
            'profit_tp1': round(p1, 1),
            'profit_tp2': round(p2, 1),
            'profit_tp3': round(p3, 1),
            'risk_pct':   round(actual_risk, 2),
            'rr_ratio':   round(p2 / actual_risk, 1) if actual_risk > 0 else 0,
            'leverage':   leverage,
            'support':    round(support,    prec) if support    else None,
            'resistance': round(resistance, prec) if resistance else None,
        }

    # ─────────────────────────────────────────────
    #  BREAKOUT CONFIRMATION
    # ─────────────────────────────────────────────

    def check_pending_confirmations(self):
        now       = time.time()
        expired   = []
        confirmed = []

        for symbol, pending in list(self.pending_signals.items()):
            if now > pending['expires_at']:
                expired.append(symbol)
                logger.info(f"⌛ EXPIRED (5min): {symbol} — discarded")
                continue
            history = self.price_history.get(symbol, [])
            if not history:
                continue
            cur           = history[-1]['price']
            confirm_price = pending['confirm_price']
            if "LONG"  in pending['direction'] and cur >= confirm_price:
                confirmed.append(symbol)
            elif "SHORT" in pending['direction'] and cur <= confirm_price:
                confirmed.append(symbol)

        for symbol in confirmed:
            pending = self.pending_signals.pop(symbol)
            signal  = pending['signal']
            history = self.price_history.get(symbol, [])
            if history:
                p    = history[-1]['price']
                prec = 6 if p < 0.01 else 4 if p < 10 else 2
                signal['entry'] = round(p, prec)
            self.redis.set(f"signal:{symbol}", json.dumps(signal))
            self.redis.publish('signals', json.dumps(signal))
            self.db.save_signal(signal)
            trading_logger.log_signal(signal)
            logger.info(
                f"✅ CONFIRMED: {symbol} {signal['direction']} | "
                f"Score:{signal['score']} | Entry:{signal['entry']}"
            )

        for symbol in expired:
            self.pending_signals.pop(symbol, None)

    # ─────────────────────────────────────────────
    #  MAIN LOOP
    # ─────────────────────────────────────────────

    def analyze_signals(self):
        while True:
            try:
                # تحقق من الإشارات المعلقة أولاً
                self.check_pending_confirmations()

                for symbol in self.symbols:
                    history = self.price_history.get(symbol, [])
                    if len(history) < 50:
                        continue

                    prices    = [p['price'] for p in history[-150:]]
                    direction = self.determine_direction(prices)
                    score, rsi, liq_detected, details, structure, bos = self.calculate_score(symbol)

                    if score < 80:
                        continue

                    macd_trend = details.get('macd_trend', 'NEUTRAL')

                    # Volume minimum
                    if details.get('volume_ratio', 0) < 1.0:
                        continue

                    # Quality gate
                    if not self.is_valid_signal(direction, rsi, macd_trend, structure, score):
                        logger.info(f"⛔ {symbol} blocked by quality gate | RSI:{rsi} MACD:{macd_trend}")
                        continue

                    price = history[-1]['price']
                    trend_4h, trend_strength = self.get_trend_from_4h(symbol)

                    # 4H strength minimum
                    if trend_4h == "NEUTRAL" or trend_strength < 55:
                        logger.info(f"⛔ {symbol} blocked — Weak/Neutral 4H trend ({trend_4h} {trend_strength}%)")
                        continue

                    regime, regime_reason = self.detect_market_regime(prices)

                    # Quality Score
                    quality  = 0
                    vol_ratio = details.get('volume_ratio', 1)
                    buy_p    = details.get('buy_pressure', 50)

                    if regime == "TRENDING":       quality += 30
                    elif regime == "WEAK_TREND":   quality += 15
                    if vol_ratio > 2:              quality += 25
                    elif vol_ratio > 1:            quality += 10
                    if "LONG"  in direction and buy_p > 60:  quality += 20
                    elif "SHORT" in direction and buy_p < 40: quality += 20
                    elif abs(buy_p - 50) > 15:               quality += 10
                    if trend_4h != "NEUTRAL":
                        if ("LONG" in direction and "LONG" in trend_4h) or \
                           ("SHORT" in direction and "SHORT" in trend_4h):
                            quality += 25
                    if score >= 90:   quality += 10
                    elif score >= 85: quality += 5

                    if quality < 60:
                        logger.info(f"⛔ {symbol} Low Quality={quality} | Regime={regime} | Vol={vol_ratio:.1f} | BP={buy_p}")
                        continue

                    # Market Regime
                    if regime in ("CHAOTIC", "WHIPSAW"):
                        logger.info(f"⛔ {symbol} blocked — Market {regime}: {regime_reason}")
                        continue
                    if regime == "RANGING" and score < 88:
                        logger.info(f"⛔ {symbol} blocked — RANGING market, score {score:.0f} < 88")
                        continue

                    # SL Guard
                    can_trade, reason = self.check_sl_guard()
                    if not can_trade:
                        logger.warning(f"⏸️ {symbol} blocked — {reason}")
                        continue

                    # Correlation Lock
                    corr_ok, corr_reason = self.check_correlation_lock(symbol, direction)
                    if not corr_ok:
                        logger.info(f"⛔ {symbol} — {corr_reason}")
                        continue

                    # BTC Correlation Filter
                    if symbol != "BTCUSDT":
                        btc_trend, btc_strength = self.get_trend_from_4h("BTCUSDT")
                        corr = self.get_btc_correlation(symbol)
                        if btc_trend != "NEUTRAL":
                            if corr > 0.8:
                                if "LONG"  in direction and "SHORT" in btc_trend:
                                    logger.info(f"⛔ {symbol} blocked — High BTC corr({corr:.2f}) + BTC SHORT")
                                    continue
                                if "SHORT" in direction and "LONG"  in btc_trend:
                                    logger.info(f"⛔ {symbol} blocked — High BTC corr({corr:.2f}) + BTC LONG")
                                    continue
                            elif corr > 0.5:
                                if "LONG"  in direction and "SHORT" in btc_trend and score < 90:
                                    logger.info(f"⛔ {symbol} blocked — Mid BTC corr({corr:.2f}) + BTC SHORT + score<90")
                                    continue
                                if "SHORT" in direction and "LONG"  in btc_trend and score < 90:
                                    logger.info(f"⛔ {symbol} blocked — Mid BTC corr({corr:.2f}) + BTC LONG + score<90")
                                    continue
                            else:
                                logger.info(f"✅ {symbol} — Low BTC corr({corr:.2f}), BTC filter skipped")

                    # Buy Pressure
                    if "LONG"  in direction and buy_p < 40: continue
                    if "SHORT" in direction and buy_p > 60: continue

                    # 4H vs 15M alignment
                    if trend_4h not in ("NEUTRAL",):
                        if ("LONG" in trend_4h) != ("LONG" in direction):
                            continue

                    # 4H score adjustment
                    adjusted_score = score
                    trend_match    = False
                    if trend_4h != "NEUTRAL":
                        if (direction == "LONG 🟢"  and trend_4h == "LONG 🟢") or \
                           (direction == "SHORT 🔴" and trend_4h == "SHORT 🔴"):
                            adjusted_score = min(100, score + 8)
                            trend_match    = True
                        else:
                            if score < 80: continue
                            adjusted_score = score - 8

                    if adjusted_score < self.min_score:
                        continue

                    # Cooldown 6h per symbol
                    now = time.time()
                    if now - self.last_signal_time.get(symbol, 0) < 21600:
                        continue

                    levels = self.calculate_trade_levels(symbol, price, adjusted_score, direction)

                    # Reason string
                    reasons = []
                    if rsi < 35:   reasons.append(f"RSI oversold ({rsi})")
                    elif rsi > 65: reasons.append(f"RSI overbought ({rsi})")
                    if "CROSS" in macd_trend: reasons.append(f"MACD {macd_trend} 🎯")
                    elif macd_trend != "NEUTRAL": reasons.append(f"MACD {macd_trend}")
                    bb_pct = details.get('bb_percent_b', 50)
                    if bb_pct < 15:   reasons.append("BB oversold")
                    elif bb_pct > 85: reasons.append("BB overbought")
                    if bos: reasons.append("BOS detected")
                    if trend_match: reasons.append("4H aligned")
                    if details.get('volume_ratio', 1) > 2:
                        reasons.append(f"Volume x{details['volume_ratio']:.1f}")
                    if liq_detected: reasons.append("Liquidation cascade 💥")

                    signal = {
                        'symbol':            symbol,
                        'score':             round(adjusted_score, 1),
                        'direction':         direction,
                        'trend_4h':          trend_4h,
                        'trend_strength':    trend_strength,
                        'trend_match':       trend_match,
                        'rsi':               round(rsi, 1),
                        'macd_trend':        macd_trend,
                        'macd_histogram':    details.get('macd_histogram', 0),
                        'bb_percent_b':      bb_pct,
                        'bb_upper':          details.get('bb_upper'),
                        'bb_lower':          details.get('bb_lower'),
                        'market_structure':  structure,
                        'bos_detected':      bos,
                        'volume_ratio':      details.get('volume_ratio', 1),
                        'buy_pressure':      details.get('buy_pressure', 50),
                        'price':             round(price, 4) if price < 1 else round(price, 2),
                        'entry':             levels['entry'],
                        'stop_loss':         levels['stop_loss'],
                        'tp1':               levels['tp1'],
                        'tp2':               levels['tp2'],
                        'tp3':               levels['tp3'],
                        'profit_tp1':        levels['profit_tp1'],
                        'profit_tp2':        levels['profit_tp2'],
                        'profit_tp3':        levels['profit_tp3'],
                        'risk_pct':          levels['risk_pct'],
                        'rr_ratio':          levels['rr_ratio'],
                        'leverage':          levels['leverage'],
                        'support':           levels['support'],
                        'resistance':        levels['resistance'],
                        'liquidation_detected': liq_detected,
                        'market_regime':     regime,
                        'quality_score':     quality,
                        'reason':            " | ".join(reasons) if reasons else "Technical confluence",
                        'time':              datetime.now().isoformat(),
                    }

                    # ── Breakout Confirmation ──────────────────────────────
                    entry_price = levels['entry']
                    if "LONG" in direction:
                        confirm_price = round(entry_price * (1 + self.CONFIRMATION_PCT), 6)
                    else:
                        confirm_price = round(entry_price * (1 - self.CONFIRMATION_PCT), 6)

                    self.pending_signals[symbol] = {
                        'signal':        signal,
                        'confirm_price': confirm_price,
                        'direction':     direction,
                        'expires_at':    now + self.CONFIRMATION_TIMEOUT
                    }
                    self.last_signal_time[symbol] = now
                    logger.info(
                        f"⏳ PENDING: {symbol} {direction} | Score:{adjusted_score} | "
                        f"Entry:{entry_price} | Confirm@:{confirm_price} | Timeout:5min"
                    )

            except Exception as e:
                trading_logger.log_error('strategy_engine.analyze_signals', e)

            time.sleep(60)

    # ─────────────────────────────────────────────
    #  HISTORICAL DATA PRELOAD
    # ─────────────────────────────────────────────

    def fetch_historical_prices(self, symbol, limit=200):
        try:
            import requests
            url    = "https://api.bybit.com/v5/market/kline"
            params = {"category": "linear", "symbol": symbol, "interval": "15", "limit": limit}
            r      = requests.get(url, params=params, timeout=10)
            data   = r.json()
            candles = data['result']['list']
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            for candle in reversed(candles):
                self.price_history[symbol].append({
                    'price': float(candle[4]), 'volume': float(candle[5]),
                    'side': 'Buy', 'time': float(candle[0]) / 1000
                })
            if len(self.price_history[symbol]) > 300:
                self.price_history[symbol] = self.price_history[symbol][-300:]

            params4h = {"category": "linear", "symbol": symbol, "interval": "240", "limit": 100}
            r4h      = requests.get(url, params=params4h, timeout=10)
            data4h   = r4h.json()
            candles4h = data4h['result']['list']
            if symbol not in self.price_history_4h:
                self.price_history_4h[symbol] = []
            for candle in reversed(candles4h):
                self.price_history_4h[symbol].append({
                    'price': float(candle[4]),
                    'time':  float(candle[0]) / 1000,
                    'period': int(float(candle[0]) / 1000 / (4 * 3600))
                })
            logger.info(f"📊 {symbol}: loaded {len(candles)} historical candles")
        except Exception as e:
            trading_logger.log_error(f"fetch_historical.{symbol}", e)

    def preload_all_symbols(self):
        logger.info(f"📡 Preloading historical data for {len(self.symbols)} symbols...")
        for symbol in self.symbols:
            self.fetch_historical_prices(symbol)
            time.sleep(0.1)
        logger.info("✅ Historical data loaded — ATR/SL will be accurate from start!")

    def start_analysis_thread(self):
        threading.Thread(target=self.analyze_signals, daemon=True).start()
