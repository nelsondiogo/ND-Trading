import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores de alta velocidade (EMA 9/21 e RSI)"""
        if not ohlcv or len(ohlcv) < 30:
            return None
        
        closes = [candle[4] for candle in ohlcv]
        opens = [candle[1] for candle in ohlcv]
        
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

        # 2. EMAs Rápidas (EMA 9 e EMA 21)
        k9 = 2 / (9 + 1)
        k21 = 2 / (21 + 1)
        ema9 = closes[0]
        ema21 = closes[0]
        for price in closes[1:]:
            ema9 = (price * k9) + (ema9 * (1 - k9))
            ema21 = (price * k21) + (ema21 * (1 - k21))

        # Estrutura das velas recentes
        curr_candle = {'open': opens[-1], 'close': closes[-1]}
        prev_candle = {'open': opens[-2], 'close': closes[-2]}

        return {
            "rsi": rsi,
            "ema9": ema9,
            "ema21": ema21,
            "curr": curr_candle,
            "prev": prev_candle,
            "close": closes[-1]
        }

    def evaluate_signal(self, indicators):
        """
        Entrada Cirúrgica: Exige o alinhamento de EMAs com confirmação de vela verde/vermelha.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        ema9 = indicators["ema9"]
        ema21 = indicators["ema21"]
        curr = indicators["curr"]
        prev = indicators["prev"]

        curr_body = curr["close"] - curr["open"]

        # LONG: EMA9 > EMA21, Vela atual verde com força e RSI em zona de arranque (45 a 65)
        if ema9 > ema21 and curr_body > 0 and 45 <= rsi <= 65:
            return "LONG"

        # SHORT: EMA9 < EMA21, Vela atual vermelha com queda e RSI em zona vendedora (35 a 55)
        if ema9 < ema21 and curr_body < 0 and 35 <= rsi <= 55:
            return "SHORT"
        
        return None

    def evaluate_exit_condition(self, pnl_pct, max_profit_reached, active_side, current_signal, leverage=17):
        """
        Regras de Saída:
        1. TAKE PROFIT FIRME: Se atinge >= 0.75% (0.0075) alavancado, fecha de imediato.
        2. Sem fecho antecipado no negativo: permite a recuperação natural do preço.
        3. Proteção de recuo no topo do lucro.
        """
        leveraged_pnl = pnl_pct * leverage
        leveraged_max_profit = max_profit_reached * leverage

        # 1. Take Profit Absoluto em 0.75%
        if leveraged_pnl >= 0.0075:
            return True, f"Take Profit 0.75% Atingido ({leveraged_pnl*100:.2f}%)"

        # Se a posição estiver no negativo, não fecha: deixa o mercado corrigir
        if pnl_pct <= 0:
            return False, None

        # 2. Mudança de Direção com Lucro
        if active_side == 'LONG' and current_signal in [None, 'SHORT']:
            return True, f"Proteção de Lucro (Sinal: {current_signal or 'NEUTRO'})"
        if active_side == 'SHORT' and current_signal in [None, 'LONG']:
            return True, f"Proteção de Lucro (Sinal: {current_signal or 'NEUTRO'})"

        # 3. Recuo do Pico de Lucro
        if leveraged_max_profit > 0.002:
            if pnl_pct < (max_profit_reached * 0.95):
                return True, f"Proteção por Recuo (Pico: {leveraged_max_profit*100:.2f}%)"

        return False, None
