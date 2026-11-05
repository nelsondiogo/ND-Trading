import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula dados de velas e indicadores de precisão milimétrica"""
        if not ohlcv or len(ohlcv) < 30:
            return None
        
        closes = [candle[4] for candle in ohlcv]
        opens = [candle[1] for candle in ohlcv]
        highs = [candle[2] for candle in ohlcv]
        lows = [candle[3] for candle in ohlcv]
        
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

        c1 = {'open': opens[-2], 'high': highs[-2], 'low': lows[-2], 'close': closes[-2]}
        c2 = {'open': opens[-1], 'high': highs[-1], 'low': lows[-1], 'close': closes[-1]}

        return {
            "rsi": rsi,
            "close": closes[-1],
            "c1": c1,
            "c2": c2
        }

    def evaluate_signal(self, indicators):
        """
        Leitura Milimétrica e Crítica de Entrada:
        - LONG: Exige que a vela anterior tenha fechado em alta ou suporte e a atual rompa o topo anterior com RSI > 50.
        - SHORT: Exige que a vela anterior tenha rejeitado o topo e a atual rompa o fundo anterior com RSI < 50.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        c1 = indicators["c1"]
        c2 = indicators["c2"]

        body_c1 = c1["close"] - c1["open"]
        body_c2 = c2["close"] - c2["open"]

        # LONG Milimétrico: Vela anterior positiva ou a corrigir para cima, e vela atual a arrancar com força compradora real
        is_long_valid = (body_c1 >= 0) and (body_c2 > 0) and (c2["close"] > c1["high"])
        if is_long_valid and rsi >= 50 and rsi <= 68:
            return "LONG"

        # SHORT Milimétrico: Vela anterior negativa ou a rejeitar topo, e vela atual a romper o fundo com força vendedora real
        is_short_valid = (body_c1 <= 0) and (body_c2 < 0) and (c2["close"] < c1["low"])
        if is_short_valid and rsi <= 50 and rsi >= 32:
            return "SHORT"
        
        return None

    def evaluate_exit_condition(self, pnl_pct, max_profit_reached, active_side, current_signal, leverage=17):
        """
        Regras de Saída Milimétricas:
        1. TAKE PROFIT FIRME: Atingiu ou ultrapassou 0.75% (0.0075) alavancado, fecha de imediato!
        2. MUDANÇA DE DIREÇÃO / NEUTRALIDADE: Fecha logo se o mercado virar contra a posição.
        3. RECUO DE LUCRO: Protege o ganho acumulado se o preço recuar do pico.
        """
        leveraged_pnl = pnl_pct * leverage
        leveraged_max_profit = max_profit_reached * leverage

        # 1. Take Profit Firme em 0.75% ou mais
        if leveraged_pnl >= 0.0075:
            return True, f"Take Profit 0.75% Atingido ({leveraged_pnl*100:.2f}%)"

        # Se estiver no prejuízo, deixamos o mercado corrigir, mas se o sinal inverter por completo, fechamos para proteger
        if pnl_pct <= 0:
            if active_side == 'LONG' and current_signal == 'SHORT':
                return True, "Proteção Cirúrgica (Inversão para SHORT no prejuízo)"
            if active_side == 'SHORT' and current_signal == 'LONG':
                return True, "Proteção Cirúrgica (Inversão para LONG no prejuízo)"
            return False, None

        # 2. Mudança de Direção ou Neutralidade com Lucro
        if active_side == 'LONG' and current_signal in [None, 'SHORT']:
            return True, f"Proteção por Mudança de Direção (Sinal: {current_signal or 'NEUTRO'})"
        
        if active_side == 'SHORT' and current_signal in [None, 'LONG']:
            return True, f"Proteção por Mudança de Direção (Sinal: {current_signal or 'NEUTRO'})"

        # 3. Recuo Firme do Pico de Lucro
        if leveraged_max_profit > 0.002:
            if pnl_pct < (max_profit_reached * 0.96):
                return True, f"Proteção Firme por Recuo (Pico: {leveraged_max_profit*100:.2f}%)"

        return False, None
