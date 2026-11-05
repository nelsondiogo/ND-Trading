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

            # Médias móveis rápidas para confirmar a direção exata do fluxo
            sma_fast = np.mean(closes[-3:])
            sma_slow = np.mean(closes[-10:])

            return {
                'rsi': float(rsi),
                'close': float(closes[-1]),
                'sma_fast': float(sma_fast),
                'sma_slow': float(sma_slow)
            }
        except Exception as e:
            logging.error(f"Erro ao calcular indicadores: {e}")
            return None

    def evaluate_signal(self, indicators):
        if not indicators:
            return "NEUTRAL"
        
        rsi = indicators.get('rsi', 50.0)
        sma_fast = indicators.get('sma_fast', 0.0)
        sma_slow = indicators.get('sma_slow', 0.0)

        # REGRA DE OURO RIGOROSA: Nunca entrar contra o mercado
        # Apenas abre LONG se houver força compradora clara (RSI > 51 e preço acima da média rápida)
        if rsi > 51.0 and sma_fast >= sma_slow:
            return "LONG"
        # Apenas abre SHORT se houver pressão vendedora clara (RSI < 49 e preço abaixo da média rápida)
        elif rsi < 49.0 and sma_fast <= sma_slow:
            return "SHORT"
        else:
            return "NEUTRAL"

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        # REGRA DE RECUO DO PICO DE LUCRO (Trailing Stop de 25% do lucro obtido)
        if max_profit_reached > 0.0010:  # Assim que ultrapassar 0.10% de lucro
            # Se o lucro atual cair abaixo de 75% do lucro máximo alcançado (perdeu 25% do topo)
            if pnl_pct <= (max_profit_reached * 0.75):
                return True

        # Stop loss de proteção estrita para evitar reversões bruscas (-0.6%)
        if pnl_pct <= -0.006:
            return True

        return False
