import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula EMAs (20 e 50) e RSI para alinhamento milimétrico com a tendência real"""
        if not ohlcv or len(ohlcv) < 55:
            return None
        
        closes = [candle[4] for candle in ohlcv]
        
        # 1. RSI (14 períodos)
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
        
        rsi = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))

        # 2. EMAs para Tendência Firme (EMA 20 e EMA 50)
        def calculate_ema(data, period):
            multiplier = 2 / (period + 1)
            ema_val = sum(data[:period]) / period
            for price in data[period:]:
                ema_val = (price - ema_val) * multiplier + ema_val
            return ema_val

        ema20 = calculate_ema(closes, 20)
        ema50 = calculate_ema(closes, 50)

        return {
            "rsi": rsi,
            "ema20": ema20,
            "ema50": ema50,
            "close": closes[-1],
            "prev_close": closes[-2]
        }

    def evaluate_signal(self, indicators):
        """
        Entrada Milimétrica:
        Só entra a favor da tendência macro definida pelo cruzamento de EMAs.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        ema20 = indicators["ema20"]
        ema50 = indicators["ema50"]
        close = indicators["close"]
        prev_close = indicators["prev_close"]

        # LONG: Tendência de alta (EMA20 > EMA50), preço a subir e RSI saudável (51 a 68)
        if ema20 > ema50 and close > prev_close and 51 <= rsi <= 68:
            return "LONG"

        # SHORT: Tendência de baixa (EMA20 < EMA50), preço a cair e RSI saudável (32 a 49)
        if ema20 < ema50 and close < prev_close and 32 <= rsi <= 49:
            return "SHORT"
        
        return None

    def evaluate_exit_condition(self, pnl_pct, max_profit_reached, active_side, current_signal, leverage=17):
        """
        Saída Estável:
        1. Take Profit em 0.75% ou mais.
        2. Proteção por recuo quando o trade está no lucro.
        3. Posição no prejuízo NUNCA é fechada prematuramente por alteração de sinal.
        """
        leveraged_pnl = pnl_pct * leverage
        leveraged_max_profit = max_profit_reached * leverage

        # 1. Take Profit Firme em 0.75% ou mais
        if leveraged_pnl >= 0.0075:
            return True, f"Take Profit 0.75% Atingido ({leveraged_pnl*100:.2f}%)"

        # Se estiver negativo, NÃO fecha por inversão de sinal (deixa o preço recuperar)
        if pnl_pct <= 0:
            return False, None

        # 2. Fecho com lucro caso o sinal inverta totalmente
        if active_side == 'LONG' and current_signal == 'SHORT':
            return True, "Proteção de Lucro (Tendência mudou para SHORT)"
        if active_side == 'SHORT' and current_signal == 'LONG':
            return True, "Proteção de Lucro (Tendência mudou para LONG)"

        # 3. Proteção por recuo do topo do lucro
        if leveraged_max_profit > 0.002:
            if pnl_pct < (max_profit_reached * 0.95):
                return True, f"Proteção por Recuo (Pico: {leveraged_max_profit*100:.2f}%)"

        return False, None
