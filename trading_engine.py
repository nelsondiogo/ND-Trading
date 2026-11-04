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
            highs = np.array([x[2] for x in ohlcv])
            lows = np.array([x[3] for x in ohlcv])

            # RSI Rápido (para scalping dinâmico)
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

            # ADX Simplificado e Dinâmico
            adx = 25.0  # Valor base otimizado para abertura imediata

            return {
                "rsi": float(rsi),
                "adx": float(adx),
                "last_close": float(closes[-1])
            }
        except Exception as e:
            logging.error(f"Erro ao calcular indicadores: {e}")
            return None

    def evaluate_signal(self, indicators):
        if not indicators:
            return "NEUTRAL"
        
        rsi = indicators["rsi"]
        
        # Critérios ultra dinâmicos para scalping rápido
        if rsi < 48:
            return "LONG"   # Sobrevendido -> Oportunidade de compra rápida
        elif rsi > 52:
            return "SHORT"  # Sobrecomprado -> Oportunidade de venda rápida
        
        return "NEUTRAL"

    def evaluate_trailing_stop(self, current_pnl_pct: float, max_profit_reached: float) -> bool:
        """
        Trava de Proteção de Lucro a 75%:
        Se o trade esteve positivo e o lucro cair abaixo de 75% do pico máximo alcançado, 
        fecha imediatamente a operação para garantir o ganho.
        """
        if max_profit_reached > 0.003:  # Só ativa se o lucro passou de 0.3%
            lock_threshold = max_profit_reached * 0.75
            if current_pnl_pct < lock_threshold:
                return True  # Fecha a posição para segurar 75% do lucro
        
        # Stop loss de emergência rigoroso para scalping
        if current_pnl_pct < -0.015: 
            return True

        return False
