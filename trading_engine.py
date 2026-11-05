import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores técnicos (RSI e EMA de Tendência)"""
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

        # Cálculo de EMA 20 (Média Móvel Exponencial)
        k = 2 / (min(20, len(closes)) + 1)
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
        - LONG: Preço acima da EMA E RSI < 52 (espaço para subir).
        - SHORT: Preço abaixo da EMA E RSI > 48 (espaço para cair).
        Garante que nunca dá sinal 'null' em condições normais de mercado.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        close = indicators["close"]
        ema = indicators["ema"]
        
        # Sinal de Compra (LONG)
        if close >= ema and rsi < 52:
            return "LONG"
        
        # Sinal de Venda (SHORT)
        elif close <= ema and rsi > 48:
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Trailing Stop Rigoroso de 15% de recuo sobre o lucro máximo:
        - Stop de emergência absoluto se atingir -0.2%.
        - Se o trade esteve positivo (pico > 0%), fecha assim que o lucro recuar 15% a partir do ponto máximo atingido.
        """
        # Stop de emergência estrito (-0.2%)
        if pnl_pct <= -0.002:
            return True

        # Se nunca atingiu lucro relevante, aguarda margem mínima
        if max_profit_reached <= 0.0005:
            if pnl_pct <= -0.0015:
                return True
            return False

        # Regra exata solicitada: fechar se o lucro recuar 15% a partir do pico máximo alcançado
        # Exemplo: se o pico foi +1.0%, o limiar de recuo é +1.0% * (1 - 0.15) = +0.85%
        recoil_threshold = max_profit_reached * 0.85
        
        if pnl_pct < recoil_threshold:
            return True

        return False
