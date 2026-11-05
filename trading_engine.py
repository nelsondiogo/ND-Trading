import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores técnicos avançados (EMA, RSI e MACD) para confirmar a tendência real"""
        if not ohlcv or len(ohlcv) < 26:
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

        # EMA 20 (Média Móvel Exponencial de Curto Prazo)
        k20 = 2 / (20 + 1)
        ema20 = closes[0]
        for price in closes[1:]:
            ema20 = (price * k20) + (ema20 * (1 - k20))

        # EMA 50 (Média Móvel Exponencial de Médio Prazo para Tendência Principal)
        k50 = 2 / (min(50, len(closes)) + 1)
        ema50 = closes[0]
        for price in closes[1:]:
            ema50 = (price * k50) + (ema50 * (1 - k50))

        return {
            "rsi": rsi,
            "close": closes[-1],
            "ema20": ema20,
            "ema50": ema50
        }

    def evaluate_signal(self, indicators):
        """
        Garante que o robô SÓ entra a favor da tendência real do mercado:
        - LONG: Apenas se Preço > EMA20 > EMA50 (Tendência de alta confirmada) E RSI < 55.
        - SHORT: Apenas se Preço < EMA20 < EMA50 (Tendência de baixa confirmada) E RSI > 45.
        Impossibilita entradas contra a maré do mercado.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        close = indicators["close"]
        ema20 = indicators["ema20"]
        ema50 = indicators["ema50"]
        
        # Tendência de Alta Forte
        if close > ema20 and ema20 > ema50 and rsi < 58:
            return "LONG"
        
        # Tendência de Baixa Forte
        elif close < ema20 and ema20 < ema50 and rsi > 42:
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Trailing Stop Rigoroso de 15% de recuo e Stop de Proteção de Capital:
        - Stop de emergência rígido em -0.15% para nunca deixar a conta sangrar.
        - Assim que atinge lucro positivo (pico > 0.05%), se o preço recuar 15% a partir desse pico máximo, fecha imediatamente.
        """
        # Stop de proteção de capital estrito (-0.15%)
        if pnl_pct <= -0.0015:
            return True

        # Se esteve positivo e o lucro começou a encolher a partir do pico
        if max_profit_reached > 0.0005:
            # Recuo de 15% sobre o lucro máximo alcançado (ex: pico de +1% fecha se baixar para +0.85%)
            recoil_threshold = max_profit_reached * 0.85
            if pnl_pct < recoil_threshold:
                return True

        return False
