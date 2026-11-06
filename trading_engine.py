import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        if not ohlcv or len(ohlcv) < 35:
            return None
        
        closes = [candle[4] for candle in ohlcv]
        opens = [candle[1] for candle in ohlcv]
        
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

        k9 = 2 / (9 + 1)
        k21 = 2 / (21 + 1)
        ema9 = closes[0]
        ema21 = closes[0]
        for price in closes[1:]:
            ema9 = (price * k9) + (ema9 * (1 - k9))
            ema21 = (price * k21) + (ema21 * (1 - k21))

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
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        ema9 = indicators["ema9"]
        ema21 = indicators["ema21"]
        c_prev = indicators["c_prev"]
        c_curr = indicators["c_curr"]

        prev_body = c_prev["close"] - c_prev["open"]
        curr_body = c_curr["close"] - c_curr["open"]

        is_long_valid = (
            ema9 > ema21 and 
            prev_body > 0 and 
            curr_body > 0 and 
            52 <= rsi <= 63
        )
        if is_long_valid:
            return "LONG"

        is_short_valid = (
            ema9 < ema21 and 
            prev_body < 0 and 
            curr_body < 0 and 
            37 <= rsi <= 48
        )
        if is_short_valid:
            return "SHORT"
        
        return None

    def evaluate_exit_condition(self, pnl_pct, max_profit_reached, active_side, current_signal, leverage=17):
        leveraged_pnl = pnl_pct * leverage
        leveraged_max_profit = max_profit_reached * leverage

        if leveraged_pnl >= 0.045:
            return True, f"Take Profit Institucional 4.5% Atingido ({leveraged_pnl*100:.2f}%)"

        if leveraged_pnl <= -0.012:
            return True, f"Stop Loss Técnico de Absorção ({leveraged_pnl*100:.2f}%)"

        if pnl_pct < 0:
            return False, None

        if leveraged_max_profit >= 0.005:
            secured_target = leveraged_max_profit * 0.70
            if leveraged_pnl < secured_target:
                return True, f"Trailing Stop Absoluto (Pico Trancado: {leveraged_max_profit*100:.2f}%)"

        if active_side == 'LONG' and current_signal == 'SHORT' and leveraged_pnl > 0:
            return True, "Proteção por Mudança de Direção com Lucro"
        if active_side == 'SHORT' and current_signal == 'LONG' and leveraged_pnl > 0:
            return True, "Proteção por Mudança de Direção com Lucro"

        return False, None
