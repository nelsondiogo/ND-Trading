import numpy as np
import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        try:
            if not ohlcv or len(ohlcv) < 15:
                return None
            
            closes = np.array([x[4] for x in ohlcv])
            delta = np.diff(closes)
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            
            avg_gain = np.mean(gain[:10])
            avg_loss = np.mean(loss[:10])
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))

            return {
                "rsi": float(rsi),
                "last_close": float(closes[-1])
            }
        except Exception as e:
            logging.error(f"Erro ao calcular indicadores: {e}")
            return None

    def evaluate_signal(self, indicators):
        if not indicators:
            return "NEUTRAL"
        
        rsi = indicators["rsi"]
        if rsi < 48:
            return "LONG"
        elif rsi > 52:
            return "SHORT"
        
        return "NEUTRAL"

    def evaluate_trailing_stop(self, current_pnl_pct: float, max_profit_reached: float) -> bool:
        if max_profit_reached > 0.003:
            lock_threshold = max_profit_reached * 0.75
            if current_pnl_pct < lock_threshold:
                return True
        if current_pnl_pct < -0.015:
            return True
        return False
