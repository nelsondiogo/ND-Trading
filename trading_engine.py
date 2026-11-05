import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores técnicos (RSI e Preço Atual)"""
        if not ohlcv or len(ohlcv) < 14:
            return None
        
        closes = [candle[4] for candle in ohlcv]
        
        # Cálculo de RSI (14 períodos)
        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))
        
        avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else sum(gains) / len(gains)
        avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else sum(losses) / len(losses)
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        # Tendência de curto prazo baseada na variação das últimas velas
        trend = "UP" if closes[-1] >= closes[-3] else "DOWN"

        return {
            "rsi": rsi,
            "close": closes[-1],
            "trend": trend
        }

    def evaluate_signal(self, indicators):
        """
        Garante disparo imediato com base no RSI e na tendência de mercado:
        - Se o RSI estiver acima de 55 ou a tendência for de queda, dispara SHORT.
        - Se o RSI estiver abaixo de 45 ou a tendência for de alta, dispara LONG.
        Elimina o estado 'AGUARDANDO' prolongado.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        trend = indicators["trend"]
        
        # Se o RSI está em sobrecompra ou tendência de baixa -> SHORT
        if rsi > 58 or trend == "DOWN":
            return "SHORT"
        
        # Se o RSI está em sobrevenda ou tendência de alta -> LONG
        elif rsi < 42 or trend == "UP":
            return "LONG"
        
        # Fallback dinâmico para garantir abertura imediata de posição
        return "SHORT" if rsi >= 50 else "LONG"

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Trailing Stop Rigoroso de 15% de recuo sobre o lucro máximo:
        - Stop de emergência imediato em -0.2%.
        - Se o trade atingiu lucro positivo, fecha assim que o lucro recuar 15% a partir do pico máximo alcançado.
        """
        if pnl_pct <= -0.002: # Stop de emergência (-0.2%)
            return True

        if max_profit_reached <= 0.0005:
            if pnl_pct <= -0.0015:
                return True
            return False

        # Regra exata: fechar se o lucro atual recuar 15% a partir do pico máximo alcançado
        recoil_threshold = max_profit_reached * 0.85
        
        if pnl_pct < recoil_threshold:
            return True

        return False
