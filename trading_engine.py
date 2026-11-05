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

        # Cálculo de EMA 20 (Média Móvel Exponencial para identificar a tendência)
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
        Avaliação bilateral rigorosa a favor da tendência:
        - LONG: Preço acima da EMA (Tendência de Alta) E RSI em zona de suporte/retração (< 48).
        - SHORT: Preço abaixo da EMA (Tendência de Baixa) E RSI em zona de resistência/sobrecompra (> 52).
        Ambas as direções têm exatamente a mesma prioridade e rigor.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        close = indicators["close"]
        ema = indicators["ema"]
        
        # Condição estrita para LONG (Compra)
        if close > ema and rsi < 48:
            return "LONG"
        
        # Condição estrita para SHORT (Venda)
        elif close < ema and rsi > 52:
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Trailing Stop ultra-rigoroso e frio:
        - Stop de emergência imediato em -0.1% para bloquear qualquer percurso negativo.
        - Assim que atinge lucro positivo (pico > +0.05%) e o preço recua 10% do pico OU toca o zero, fecha imediatamente para trancar o lucro.
        """
        # Stop de emergência estrito (-0.1%)
        if pnl_pct <= -0.001:
            return True

        # Se esteve positivo e o preço começa a voltar para trás
        if max_profit_reached > 0.0005:
            if pnl_pct < (max_profit_reached * 0.90) or pnl_pct <= 0:
                return True

        return False
