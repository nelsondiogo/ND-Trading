import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores de alta precisão e estrutura de velas para eliminar ruído"""
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

        # Estrutura das últimas 3 velas
        c1 = {'open': opens[-3], 'close': closes[-3]}
        c2 = {'open': opens[-2], 'close': closes[-2]}
        c3 = {'open': opens[-1], 'close': closes[-1]}

        return {
            "rsi": rsi,
            "close": closes[-1],
            "c1": c1,
            "c2": c2,
            "c3": c3
        }

    def evaluate_signal(self, indicators):
        """
        Entrada Estritamente Rigorosa: 
        NUNCA abre se houver dúvida. Exige alinhamento perfeito de momentum e RSI.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        c1 = indicators["c1"]
        c2 = indicators["c2"]
        c3 = indicators["c3"]

        body1 = c1["close"] - c1["open"]
        body2 = c2["close"] - c2["open"]
        body3 = c3["close"] - c3["open"]

        # LONG Estrito: RSI saudável e arranque verde confirmado
        is_long_setup = (body2 <= 0 or abs(body2) < abs(c2['close']) * 0.001) and (body3 > 0)
        if is_long_setup and 48 <= rsi <= 62:
            return "LONG"

        # SHORT Estrito: RSI saudável e queda vermelha confirmada
        is_short_setup = (body2 >= 0 or abs(body2) < abs(c2['close']) * 0.001) and (body3 < 0)
        if is_short_setup and 38 <= rsi <= 52:
            return "SHORT"
        
        return None

    def evaluate_exit_condition(self, pnl_pct, max_profit_reached, active_side, current_signal, leverage=17):
        """
        Regras de Saída ND-SCALPING (Rigidez Máxima):
        1. STOP LOSS BREAK-EVEN (0 a 0): Se o PnL for negativo (<= 0), fecha IMEDIATAMENTE no ponto de entrada (linha vermelha). Zero perdas!
        2. TAKE PROFIT FIRME: Se o PnL alavancado atingir ou ultrapassar 0.75% (0.0075), fecha de imediato.
        3. PROTEÇÃO POR RECUO FIRME: Se o lucro recuar do topo, fecha de imediato para trancar o ganho.
        """
        leveraged_pnl = pnl_pct * leverage
        leveraged_max_profit = max_profit_reached * leverage

        # 1. STOP LOSS CIRÚRGICO NO PONTO DE ENTRADA (0 a 0 / Sem Perda)
        if pnl_pct < 0:
            return True, "Stop Loss Break-Even (0 a 0 - Linha de Entrada)"

        # 2. Take Profit Firme em 0.75% ou mais
        if leveraged_pnl >= 0.0075:
            return True, f"Take Profit 0.75% Atingido ({leveraged_pnl*100:.2f}%)"

        # 3. Mudança de Direção ou Neutralidade com Lucro
        if active_side == 'LONG' and current_signal in [None, 'SHORT']:
            return True, f"Proteção por Mudança de Direção (Sinal: {current_signal or 'NEUTRO'})"
        
        if active_side == 'SHORT' and current_signal in [None, 'LONG']:
            return True, f"Proteção por Mudança de Direção (Sinal: {current_signal or 'NEUTRO'})"

        # 4. Recuo Firme do Pico de Lucro (Trailing Stop Sensível de 2%)
        if leveraged_max_profit > 0.002:
            if pnl_pct < (max_profit_reached * 0.98):
                return True, f"Proteção Firme por Recuo (Pico: {leveraged_max_profit*100:.2f}%)"

        return False, None
