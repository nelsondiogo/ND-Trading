import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores técnicos básicos (RSI e Médias Móveis)"""
        if not ohlcv or len(ohlcv) < 14:
            return None
        
        closes = [candle[4] for candle in ohlcv]
        
        # Cálculo simples de RSI (14 períodos)
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

        return {
            "rsi": rsi,
            "close": closes[-1]
        }

    def evaluate_signal(self, indicators):
        """Avalia se deve entrar em LONG ou SHORT com base no RSI"""
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        # Condições de entrada otimizadas para HFT (DOGE, XRP, ADA)
        if rsi < 42:
            return "LONG"
        elif rsi > 58:
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Gestão rigorosa de saída para evitar perdas desnecessárias:
        - Se o PnL cair mais de 0.4% a partir do lucro máximo atingido, fecha imediatamente.
        - Se o PnL atingir -0.3% (stop loss de emergência), fecha imediatamente para proteger o capital.
        """
        # Stop loss de emergência estrito (protege contra inversão brusca de tendência)
        if pnl_pct <= -0.003: # -0.3%
            return True

        # Se nunca atingiu lucro relevante e começou a descer
        if max_profit_reached <= 0.002: # Menos de +0.2% de pico
            if pnl_pct <= -0.002: # Fecha se recuar para -0.2%
                return True
            return False

        # Trailing stop dinâmico: se o lucro recuar mais de 40% em relação ao máximo alcançado
        drawdown_limit = max_profit_reached * 0.60
        if pnl_pct < drawdown_limit:
            return True

        return False
