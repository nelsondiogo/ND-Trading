import numpy as np
import logging

class TradingEngine:
    def __init__(self, config_module):
        self.config = config_module

    def calculate_indicators(self, ohlcv):
        if not ohlcv or len(ohlcv) < 14:
            return None
        
        try:
            closes = np.array([float(candle[4]) for candle in ohlcv])
            deltas = np.diff(closes)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)

            avg_gain = np.mean(gains[-14:])
            avg_loss = np.mean(losses[-14:])

            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))

            return {'rsi': float(rsi), 'close': float(closes[-1])}
        except Exception as e:
            logging.error(f"Erro ao calcular indicadores: {e}")
            return None

    def evaluate_signal(self, indicators):
        if not indicators:
            return "NEUTRAL"
        
        rsi = indicators.get('rsi', 50.0)

        # Parâmetros otimizados para Scalping HFT (Disparo rápido)
        if rsi < 48:
            return "LONG"
        elif rsi > 52:
            return "SHORT"
        else:
            return "LONG"  # Força entrada se o mercado estiver perto da média

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        # Trava de lucro (Take Profit a 0.5% ou Trailing Stop com recuo de 25%)
        if pnl_pct >= 0.005:  
            return True
        if max_profit_reached >= 0.003 and pnl_pct <= (max_profit_reached * 0.75):
            return True
        # Stop Loss de segurança a -1.5%
        if pnl_pct <= -0.015:
            return True
        return False
