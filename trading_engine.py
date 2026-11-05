import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores de alta velocidade para Scalping (EMA 9, EMA 21 e RSI)"""
        if not ohlcv or len(ohlcv) < 30:
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

        # EMA 9 (Curta e Rápida)
        k9 = 2 / (9 + 1)
        ema9 = closes[0]
        for price in closes[1:]:
            ema9 = (price * k9) + (ema9 * (1 - k9))

        # EMA 21 (Média)
        k21 = 2 / (21 + 1)
        ema21 = closes[0]
        for price in closes[1:]:
            ema21 = (price * k21) + (ema21 * (1 - k21))

        return {
            "rsi": rsi,
            "close": closes[-1],
            "ema9": ema9,
            "ema21": ema21
        }

    def evaluate_signal(self, indicators):
        """
        Filtro Ultra-Rigoroso para Scalping (Evita entradas falsas):
        - LONG: EMA9 > EMA21 E RSI entre 45 e 65.
        - SHORT: EMA9 < EMA21 E RSI entre 35 e 55.
        """
        if not indicators:
            return None
        
        close = indicators["close"]
        ema9 = indicators["ema9"]
        ema21 = indicators["ema21"]
        rsi = indicators["rsi"]
        
        if ema9 > ema21 and 45 <= rsi <= 65:
            return "LONG"
        elif ema9 < ema21 and 35 <= rsi <= 55:
            return "SHORT"
        
        return None

    def evaluate_exit_condition(self, pnl_pct, max_profit_reached, active_side, current_signal, leverage=17):
        """
        Regras de Saída ND-SCALPING (Proteção Máxima de Lucro):
        1. Proibido fechar no negativo (pnl_pct <= 0 mantém aberto para recuperar).
        2. TAKE PROFIT IMEDIATO EM 0.75%: Se o PnL alavancado atingir >= 0.75% (0.0075), fecha de imediato!
        3. PROTEÇÃO POR REVERSÃO / NEUTRALIDADE: Se o mercado ficar neutro ou inverter e estiver no lucro, fecha logo.
        4. PROTEÇÃO POR RECUO DE LUCRO: Se o preço recuar ligeiramente do pico de lucro (recuo de 3%), fecha de imediato para não devolver nada!
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

        # 3. Recuo Imediato do Pico de Lucro (Trailing Stop Ultra-Sensível de 3%)
        if leveraged_max_profit > 0.002: # Se já esteve com lucro superior a 0.2%
            # Se o lucro atual caiu mais de 3% em relação ao máximo atingido
            if pnl_pct < (max_profit_reached * 0.97):
                return True, f"Proteção por Recuo (Pico: {leveraged_max_profit*100:.2f}%)"

        return False, None
