import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        if not ohlcv or len(ohlcv) < 14:
            return None
        
        closes = [candle[4] for candle in ohlcv]
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
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        if rsi < 42:
            return "LONG"
        elif rsi > 58:
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Regra rigorosa de Trailing Stop:
        - Só atua se o robô já tiver alcançado algum lucro (> 0%).
        - Se o preço recuar 15% ou mais a partir do lucro máximo obtido (pico), dispara o fecho imediato.
        - Exemplo: Se o lucro máximo foi de +1.0%, o stop é ativado se o lucro cair abaixo de +0.85% (perdeu 15% do ganho de pico).
        - Stop de emergência absoluto se cair para -0.3% para travar perdas imprevistas.
        """
        # Stop de emergência fixo contra inversões agressivas de mercado
        if pnl_pct <= -0.003:
            return True

        # Se nunca esteve positivo o suficiente, aguarda ou protege no limiar mínimo
        if max_profit_reached <= 0.001: # Menos de +0.1% de pico
            if pnl_pct <= -0.0015:
                return True
            return False

        # Regra exata: se o PnL atual recuou 15% do lucro máximo atingido
        # Limiar de recuo = max_profit_reached * (1 - 0.15) -> max_profit_reached * 0.85
        recoil_threshold = max_profit_reached * 0.85
        
        if pnl_pct < recoil_threshold:
            return True

        return False
