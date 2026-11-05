import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores de altíssima precisão e confirmação de velas para Scalping"""
        if not ohlcv or len(ohlcv) < 30:
            return None
        
        closes = [candle[4] for candle in ohlcv]
        opens = [candle[1] for candle in ohlcv]
        highs = [candle[2] for candle in ohlcv]
        lows = [candle[3] for candle in ohlcv]
        
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

        # 2. EMAs Rápidas (EMA 9 e EMA 21) para Tendência de Curto Prazo
        k9 = 2 / (9 + 1)
        k21 = 2 / (21 + 1)
        ema9 = closes[0]
        ema21 = closes[0]
        for price in closes[1:]:
            ema9 = (price * k9) + (ema9 * (1 - k9))
            ema21 = (price * k21) + (ema21 * (1 - k21))

        # 3. Ação de Preço Estrita (Últimas 2 velas)
        c_prev = {'open': opens[-2], 'close': closes[-2]}
        c_curr = {'open': opens[-1], 'close': closes[-1]}

        return {
            "rsi": rsi,
            "ema9": ema9,
            "ema21": ema21,
            "c_prev": c_prev,
            "c_curr": c_curr,
            "close": closes[-1]
        }

    def evaluate_signal(self, indicators):
        """
        Entrada com Rigor Extremo:
        Exige alinhamento perfeito de EMAs, velas consecutivas confirmadas e RSI restrito.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        ema9 = indicators["ema9"]
        ema21 = indicators["ema21"]
        c_prev = indicators["c_prev"]
        c_curr = indicators["c_curr"]

        prev_body = c_prev["close"] - c_prev["open"]
        curr_body = c_curr["close"] - c_curr["open"]

        # LONG com Rigor Extremo: EMA9 > EMA21, duas velas consecutivas verdes e RSI estrito (52 a 65)
        is_long_valid = (
            ema9 > ema21 and 
            prev_body > 0 and 
            curr_body > 0 and 
            52 <= rsi <= 65
        )
        if is_long_valid:
            return "LONG"

        # SHORT com Rigor Extremo: EMA9 < EMA21, duas velas consecutivas vermelhas e RSI estrito (35 a 48)
        is_short_valid = (
            ema9 < ema21 and 
            prev_body < 0 and 
            curr_body < 0 and 
            35 <= rsi <= 48
        )
        if is_short_valid:
            return "SHORT"
        
        return None

    def evaluate_exit_condition(self, pnl_pct, max_profit_reached, active_side, current_signal, leverage=17):
        """
        Regras de Saída Blindadas:
        1. TAKE PROFIT FIRME: Atingiu ou ultrapassou 0.75% (0.0075) alavancado, fecha IMEDIATAMENTE.
        2. STOP DE SEGURANÇA DE EMERGÊNCIA: Se o PnL alavancado atingir -5% (-0.05), corta para proteger a banca.
        3. Proteção por recuo de topo e mudança de direção com lucro.
        """
        leveraged_pnl = pnl_pct * leverage
        leveraged_max_profit = max_profit_reached * leverage

        # 1. Take Profit Absoluto em 0.75% ou mais
        if leveraged_pnl >= 0.0075:
            return True, f"Take Profit 0.75% Atingido ({leveraged_pnl*100:.2f}%)"

        # 2. Stop de Segurança contra Drawdown Extremo (Proteção de Capital)
        if leveraged_pnl <= -0.05:
            return True, f"Stop de Segurança de Emergência ({leveraged_pnl*100:.2f}%)"

        if pnl_pct <= 0:
            return False, None

        # 3. Mudança de Direção com Lucro
        if active_side == 'LONG' and current_signal in [None, 'SHORT']:
            return True, f"Proteção por Mudança de Direção (Sinal: {current_signal or 'NEUTRO'})"
        if active_side == 'SHORT' and current_signal in [None, 'LONG']:
            return True, f"Proteção por Mudança de Direção (Sinal: {current_signal or 'NEUTRO'})"

        # 4. Recuo do Pico de Lucro
        if leveraged_max_profit > 0.002:
            if pnl_pct < (max_profit_reached * 0.95):
                return True, f"Proteção por Recuo (Pico: {leveraged_max_profit*100:.2f}%)"

        return False, None
