import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores técnicos avançados (RSI e EMA de Tendência)"""
        if not ohlcv or len(ohlcv) < 20:
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

        # Cálculo de EMA 20 (Média Móvel Exponencial para identificar a tendência do mercado)
        k = 2 / (20 + 1)
        ema = closes[0]
        for price in closes[1:]:
            ema = (price * k) + (ema * (1 - k))

        return {
            "rsi": rsi,
            "close": closes[-1],
            "ema": ema
        }

    def evaluate_signal(self, indicators):
        """
        Avaliação rigorosa de entrada a favor da tendência:
        - LONG (Compra): RSI em sobrevenda (< 45) E preço atual acima da EMA (tendência de alta confirmada).
        - SHORT (Venda): RSI em sobrecompra (> 55) E preço atual abaixo da EMA (tendência de baixa confirmada).
        Isto elimina totalmente entradas contra a maré do mercado.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        close = indicators["close"]
        ema = indicators["ema"]
        
        # Só abre LONG se o mercado estiver em alta (preço > EMA) e RSI indicar suporte
        if rsi < 45 and close > ema:
            return "LONG"
        
        # Só abre SHORT se o mercado estiver em baixa (preço < EMA) e RSI indicar resistência
        elif rsi > 55 and close < ema:
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Trailing Stop rigoroso de 15% de recuo sobre o lucro máximo:
        - Protege o ganho obtido assim que o preço recua 15% do pico máximo.
        - Corta perdas imediatamente com stop de emergência em -0.3%.
        """
        if pnl_pct <= -0.003: # Stop de emergência (-0.3%)
            return True

        if max_profit_reached <= 0.001: # Se o lucro de pico for menor que +0.1%
            if pnl_pct <= -0.0015:
                return True
            return False

        # Regra exata: disparo se o lucro atual recuar 15% do pico máximo alcançado
        recoil_threshold = max_profit_reached * 0.85
        
        if pnl_pct < recoil_threshold:
            return True

        return False
