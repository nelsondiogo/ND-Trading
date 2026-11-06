import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config
        self.active_stop_price = 0.0
        self.peak_price = 0.0

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores técnicos de alta frequência para scalping"""
        if not ohlcv or len(ohlcv) < 14:
            return {"close": 0.0, "rsi": 50.0, "high": 0.0, "low": 0.0}
        
        closes = [candle[4] for candle in ohlcv]
        current_close = closes[-1]
        
        gains, losses = 0.0, 0.0
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            if diff > 0: gains += diff
            else: losses -= diff
        
        rs = (gains / 14) / ((losses / 14) if losses != 0 else 1)
        rsi = 100 - (100 / (1 + rs))
        
        return {
            "close": current_close,
            "rsi": rsi,
            "high": max(closes[-5:]),
            "low": min(closes[-5:])
        }

    def evaluate_signal(self, indicators):
        """Avalia sinais de entrada institucionais para Long ou Short"""
        rsi = indicators["rsi"]
        if rsi < 35:
            return "LONG"
        elif rsi > 65:
            return "SHORT"
        return None

    def manage_trailing_stop(self, position, current_price):
        """
        Mecanismo Trailing Stop Ratchet:
        - Segue o lucro após atingir 0.5%
        - Trava móvel fixada no cume do preço máximo
        - Encerra no Take Profit de 4.5% ou Stop Loss de 1.2%
        """
        side = position["side"]
        entry = position["entry"]
        
        if side == "LONG":
            profit_pct = (current_price - entry) / entry
            if current_price > self.peak_price:
                self.peak_price = current_price
                
            if profit_pct >= 0.005:
                potential_stop = self.peak_price * (1 - 0.003)
                if potential_stop > self.active_stop_price:
                    self.active_stop_price = potential_stop
                    
            if profit_pct >= 0.045:
                return "CLOSE_TP"
            if current_price <= (entry * (1 - 0.012)):
                return "CLOSE_SL"
                
        elif side == "SHORT":
            profit_pct = (entry - current_price) / entry
            if self.peak_price == 0.0 or current_price < self.peak_price:
                self.peak_price = current_price
                
            if profit_pct >= 0.005:
                potential_stop = self.peak_price * (1 + 0.003)
                if self.active_stop_price == 0.0 or potential_stop < self.active_stop_price:
                    self.active_stop_price = potential_stop
                    
            if profit_pct >= 0.045:
                return "CLOSE_TP"
            if current_price >= (entry * (1 + 0.012)):
                return "CLOSE_SL"
                
        return "HOLD"
