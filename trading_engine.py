import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula dados de velas de alta precisão para Scalping Cirúrgico"""
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

        # Estrutura das últimas velas para detetar exaustão e correção exata
        current_candle = {'open': opens[-1], 'high': highs[-1], 'low': lows[-1], 'close': closes[-1]}
        previous_candle = {'open': opens[-2], 'high': highs[-2], 'low': lows[-2], 'close': closes[-2]}

        return {
            "rsi": rsi,
            "close": closes[-1],
            "current": current_candle,
            "previous": previous_candle
        }

    def evaluate_signal(self, indicators):
        """
        Entrada Cirúrgica Anti-Drawdown:
        Só entra após a vela anterior ter corrigido/testado o patamar oposto.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        curr = indicators["current"]
        prev = indicators["previous"]

        curr_body = curr["close"] - curr["open"]
        prev_upper_shadow = prev["high"] - max(prev["open"], prev["close"])
        prev_lower_shadow = min(prev["open"], prev["close"]) - prev["low"]

        # LONG Cirúrgico: Vela anterior testoubaixo (pavio inferior forte) e a atual arrancou verde
        is_long_setup = (prev_lower_shadow > prev_upper_shadow) and (curr_body > 0)
        if is_long_setup and 42 <= rsi <= 65:
            return "LONG"

        # SHORT Cirúrgico: Vela anterior testou alto (pavio superior forte) e a atual arrancou vermelha
        is_short_setup = (prev_upper_shadow > prev_lower_shadow) and (curr_body < 0)
        if is_short_setup and 35 <= rsi <= 58:
            return "SHORT"
        
        return None

    def evaluate_exit_condition(self, pnl_pct, max_profit_reached, active_side, current_signal, leverage=17):
        """
        Regras de Saída ND-SCALPING (Blindagem Total):
        1. STOP LOSS DE EMERGÊNCIA: Se o PnL alavancado descer abaixo de -1.5% (-0.015), corta imediatamente para evitar desastres!
        2. TAKE PROFIT ABSOLUTO EM 0.75%: Se atingir >= 0.75% (0.0075), fecha de imediato.
        3. MUDANÇA DE DIREÇÃO / NEUTRALIDADE: Fecha logo se o sinal mudar.
        4. RECUO DE LUCRO: Protege o lucro obtido mal o preço recue do topo.
        """
        leveraged_pnl = pnl_pct * leverage
        leveraged_max_profit = max_profit_reached * leverage

        # 1. STOP LOSS DE EMERGÊNCIA (Proteção rigorosa contra drawdowns profundos)
        if leveraged_pnl <= -0.015:
            return True, f"Stop Loss de Emergência Acionado ({leveraged_pnl*100:.2f}%)"

        if pnl_pct <= 0:
            return False, None

        # 2. Take Profit Absoluto em 0.75% (Sem espera)
        if leveraged_pnl >= 0.0075:
            return True, f"Take Profit 0.75% Atingido ({leveraged_pnl*100:.2f}%)"

        # 3. Mudança de Direção ou Neutralidade com Lucro
        if active_side == 'LONG' and current_signal in [None, 'SHORT']:
            return True, f"Proteção (Sinal mudou para {current_signal or 'NEUTRO'})"
        
        if active_side == 'SHORT' and current_signal in [None, 'LONG']:
            return True, f"Proteção (Sinal mudou para {current_signal or 'NEUTRO'})"

        # 4. Recuo Imediato do Pico de Lucro (Trailing Stop de Proteção de 3%)
        if leveraged_max_profit > 0.002:
            if pnl_pct < (max_profit_reached * 0.97):
                return True, f"Proteção por Recuo (Pico: {leveraged_max_profit*100:.2f}%)"

        return False, None
