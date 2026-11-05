import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores técnicos avançados (EMA e RSI) para evitar entradas erradas"""
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

        # EMA 20 (Curto Prazo)
        k20 = 2 / (20 + 1)
        ema20 = closes[0]
        for price in closes[1:]:
            ema20 = (price * k20) + (ema20 * (1 - k20))

        # EMA 50 (Médio Prazo)
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
        Filtro de entrada estrito para eliminar entradas erradas no negativo:
        - LONG: Apenas se Preço > EMA20 > EMA50 E RSI < 60 (Garante tendência forte de alta).
        - SHORT: Apenas se Preço < EMA20 < EMA50 E RSI > 40 (Garante tendência forte de baixa).
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        close = indicators["close"]
        ema20 = indicators["ema20"]
        ema50 = indicators["ema50"]
        
        # Tendência de Alta Confirmada
        if close > ema20 and ema20 > ema50 and rsi < 60:
            return "LONG"
        
        # Tendência de Baixa Confirmada
        elif close < ema20 and ema20 < ema50 and rsi > 40:
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Stop Autónomo Rigoroso:
        - Stop de proteção de capital em -0.15%.
        - Trailing stop de recuo de 15% ativado após superar +0.20% de lucro.
        """
        if pnl_pct <= -0.0015:
            return True, "Stop de Proteção de Capital (-0.15%)"

        if max_profit_reached >= 0.002:
            recoil_threshold = max_profit_reached * 0.85
            if pnl_pct < recoil_threshold:
                return True, "Trailing Stop Automático (Recuo de Lucro)"

        return False, None
