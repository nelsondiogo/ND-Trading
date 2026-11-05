import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores avançados (EMA, RSI e MACD) para seguir rigorosamente a tendência"""
        if not ohlcv or len(ohlcv) < 35:
            return None
        
        closes = [candle[4] for candle in ohlcv]
        
        # RSI (14 períodos)
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

        # EMA 12 e EMA 26 (para MACD)
        k12 = 2 / (12 + 1)
        k26 = 2 / (26 + 1)
        ema12 = closes[0]
        ema26 = closes[0]
        for price in closes[1:]:
            ema12 = (price * k12) + (ema12 * (1 - k12))
            ema26 = (price * k26) + (ema26 * (1 - k26))
        
        macd_line = ema12 - ema26

        # EMA 50 (Tendência de Médio Prazo)
        k50 = 2 / (min(50, len(closes)) + 1)
        ema50 = closes[0]
        for price in closes[1:]:
            ema50 = (price * k50) + (ema50 * (1 - k50))

        return {
            "rsi": rsi,
            "close": closes[-1],
            "macd": macd_line,
            "ema50": ema50
        }

    def evaluate_signal(self, indicators):
        """
        Gatilho infalível anti-erro:
        - LONG: Apenas se o preço estiver acima da EMA50 E o MACD for positivo (Tendência clara de alta).
        - SHORT: Apenas se o preço estiver abaixo da EMA50 E o MACD for negativo (Tendência clara de baixa).
        """
        if not indicators:
            return None
        
        close = indicators["close"]
        ema50 = indicators["ema50"]
        macd = indicators["macd"]
        rsi = indicators["rsi"]
        
        # Tendência de Alta Inquestionável
        if close > ema50 and macd > 0 and rsi < 70:
            return "LONG"
        
        # Tendência de Baixa Inquestionável
        elif close < ema50 and macd < 0 and rsi > 30:
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Stop de Proteção e Trailing Stop Rigoroso:
        - Fecha imediatamente se a perda atingir -0.15%.
        - Ativa o trailing stop mal o lucro supere +0.20%, recuando no máximo 15% a partir do pico.
        """
        if pnl_pct <= -0.0015:
            return True, "Stop de Proteção de Capital (-0.15%)"

        if max_profit_reached >= 0.002:
            recoil_threshold = max_profit_reached * 0.85
            if pnl_pct < recoil_threshold:
                return True, "Trailing Stop Automático (Recuo de Lucro)"

        return False, None
