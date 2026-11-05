import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores técnicos avançados (EMA, RSI) para alta precisão de tendência"""
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

        # EMA 20
        k20 = 2 / (20 + 1)
        ema20 = closes[0]
        for price in closes[1:]:
            ema20 = (price * k20) + (ema20 * (1 - k20))

        # EMA 50
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
        """Entradas alinhadas com a tendência real (EMA + RSI)"""
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        close = indicators["close"]
        ema20 = indicators["ema20"]
        ema50 = indicators["ema50"]
        
        # Tendência de Alta
        if close > ema20 and ema20 > ema50 and rsi < 58:
            return "LONG"
        
        # Tendência de Baixa
        elif close < ema20 and ema20 < ema50 and rsi > 42:
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Trailing Stop Blindado e Cobertura de Taxas:
        - Stop de proteção de capital em -0.15%.
        - O trailing stop de recuo (15%) só atua de forma a garantir lucro líquido real após o pico superar +0.30%.
        """
        # Stop de proteção contra quedas bruscas (-0.15%)
        if pnl_pct <= -0.0015:
            return True

        # Só ativa o trailing de lucro se o trade já esteve confortavelmente positivo (> +0.30%)
        if max_profit_reached >= 0.003:
            # Recuo de 15% sobre o pico máximo alcançado
            recoil_threshold = max_profit_reached * 0.85
            if pnl_pct < recoil_threshold:
                return True

        return False
