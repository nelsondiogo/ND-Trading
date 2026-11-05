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

            # Tendência de curto prazo via Média Móvel Simples (SMA 5 vs SMA 15)
            sma_fast = np.mean(closes[-5:])
            sma_slow = np.mean(closes[-15:])

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

        # Regra de Ouro: Só entra a favor da tendência real de mercado
        if rsi > 52 and sma_fast > sma_slow:
            return "LONG"
        elif rsi < 48 and sma_fast < sma_slow:
            return "SHORT"
        else:
            return "NEUTRAL"

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        # REGRA DE OURO DA SAÍDA:
        # Se atingiu lucro positivo (ex: > 0.15%), e o preço recuar 25% desse topo -> FECHA IMEDIATAMENTE
        if max_profit_reached > 0.0015:
            lucro_restante = pnl_pct / max_profit_reached
            if lucro_restante <= 0.75:  # Perdeu 25% do topo alcançado
                return True

        # Stop Loss de emergência caso a operação entre logo a perder (-0.8%)
        if pnl_pct <= -0.008:
            return True

        return False
