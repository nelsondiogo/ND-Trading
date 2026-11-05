import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula dados de velas e momentum cirúrgico para Scalping"""
        if not ohlcv or len(ohlcv) < 20:
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

        # Análise das últimas 2 Velas para Entrada Cirúrgica (Pullback)
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
        Entrada Cirúrgica Baseada em Velas (Aguarda correção antes de seguir a direção):
        - LONG: A vela anterior corrigiu (ou fechou neutra/leve baixa) e a atual está a arrancar em alta com força.
        - SHORT: A vela anterior corrigiu (ou subiu levemente) e a atual está a romper em queda.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        curr = indicators["current"]
        prev = indicators["previous"]

        curr_body = curr["close"] - curr["open"]
        prev_body = prev["close"] - prev["open"]

        # Condição LONG Cirúrgica: Correção na vela anterior (prev_body <= 0 ou pequena) e arranque verde agora
        is_long_pullback = (prev_body <= 0 or prev_body < abs(prev['close']) * 0.001) and (curr_body > 0)
        if is_long_pullback and 40 <= rsi <= 68:
            return "LONG"

        # Condição SHORT Cirúrgica: Correção na vela anterior (prev_body >= 0) e queda agora
        is_short_pullback = (prev_body >= 0 or prev_body > -abs(prev['close']) * 0.001) and (curr_body < 0)
        if is_short_pullback and 32 <= rsi <= 60:
            return "SHORT"
        
        return None

    def evaluate_exit_condition(self, pnl_pct, max_profit_reached, active_side, current_signal, leverage=17):
        """
        Regras de Saída ND-SCALPING (Trava Rígida em 0.75% & Proteção Imediata):
        1. Proibido fechar no negativo (pnl_pct <= 0 mantém aberto até recuperar).
        2. TAKE PROFIT ABSOLUTO EM 0.75%: Se o PnL alavancado atingir >= 0.75% (0.0075), fecha de imediato!
        3. MUDANÇA DE DIREÇÃO / NEUTRALIDADE: Fecha logo se o mercado virar.
        4. RECUO DE LUCRO: Se o lucro recuar do topo, fecha de imediato para não devolver ganho.
        """
        if pnl_pct <= 0:
            return False, None

        leveraged_pnl = pnl_pct * leverage
        leveraged_max_profit = max_profit_reached * leverage

        # 1. Take Profit Absoluto em 0.75% (Sem espera)
        if leveraged_pnl >= 0.0075:
            return True, f"Take Profit 0.75% Atingido ({leveraged_pnl*100:.2f}%)"

        # 2. Mudança de Direção ou Neutralidade com Lucro
        if active_side == 'LONG' and current_signal in [None, 'SHORT']:
            return True, f"Proteção (Sinal mudou para {current_signal or 'NEUTRO'})"
        
        if active_side == 'SHORT' and current_signal in [None, 'LONG']:
            return True, f"Proteção (Sinal mudou para {current_signal or 'NEUTRO'})"

        # 3. Recuo Imediato do Pico de Lucro (Trailing Stop de Proteção de 3%)
        if leveraged_max_profit > 0.002:
            if pnl_pct < (max_profit_reached * 0.97):
                return True, f"Proteção por Recuo (Pico: {leveraged_max_profit*100:.2f}%)"

        return False, None
