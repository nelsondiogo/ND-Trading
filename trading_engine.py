import logging
import numpy as np

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        if not ohlcv or len(ohlcv) < 30:
            return None
        closes = np.array([candle[4] for candle in ohlcv])
        volumes = np.array([candle[5] for candle in ohlcv])
        highs = np.array([candle[2] for candle in ohlcv])
        lows = np.array([candle[3] for candle in ohlcv])

        ema_fast = self._calculate_ema(closes, 9)
        ema_slow = self._calculate_ema(closes, 21)
        rsi = self._calculate_rsi(closes, 14)
        mfi = self._calculate_mfi(highs, lows, closes, volumes, 14)
        adx = self._calculate_adx(highs, lows, closes, 14)

        return {
            'ema_fast': ema_fast[-1], 'ema_slow': ema_slow[-1],
            'rsi': rsi[-1], 'mfi': mfi[-1], 'adx': adx[-1]
        }

    def evaluate_signal(self, indicators):
        if not indicators:
            return 'NEUTRAL'
        adx_strong = indicators['adx'] > self.config.ADX_THRESHOLD
        trend_long = indicators['ema_fast'] > indicators['ema_slow']
        trend_short = indicators['ema_fast'] < indicators['ema_slow']

        if adx_strong and trend_long and indicators['rsi'] < 70 and indicators['mfi'] > 40:
            return 'LONG'
        elif adx_strong and trend_short and indicators['rsi'] > 30 and indicators['mfi'] < 60:
            return 'SHORT'
        return 'NEUTRAL'

    def evaluate_trailing_stop(self, current_pnl_percent, max_profit_reached):
        if max_profit_reached >= self.config.TRAILING_ACTIVATION_THRESHOLD:
            allowed_drawdown = max_profit_reached * (1.0 - self.config.TRAILING_DRAWDOWN_PERCENT)
            if current_pnl_percent <= allowed_drawdown:
                return True 
        return False

    def _calculate_ema(self, data, period):
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        a = np.convolve(data, weights, mode='full')[:len(data)]
        a[:period] = a[period]
        return a

    def _calculate_rsi(self, closes, period=14):
        deltas = np.diff(closes)
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum()/period
        down = -seed[seed < 0].sum()/period
        rs = up/down if down != 0 else 0
        rsi = np.zeros_like(closes)
        rsi[:period] = 100. - 105./(1. + rs)
        for i in range(period, len(closes)):
            delta = deltas[i - 1]
            upval = delta if delta > 0 else 0.
            downval = -delta if delta < 0 else 0.
            up = (up*(period - 1) + upval)/period
            down = (down*(period - 1) + downval)/period
            rs = up/down if down != 0 else 0
            rsi[i] = 100. - 100./(1. + rs)
        return rsi

    def _calculate_mfi(self, highs, lows, closes, volumes, period=14):
        typical_price = (highs + lows + closes) / 3
        money_flow = typical_price * volumes
        positive_flow = np.zeros_like(closes)
        negative_flow = np.zeros_like(closes)
        for i in range(1, len(closes)):
            if typical_price[i] > typical_price[i-1]:
                positive_flow[i] = money_flow[i]
            elif typical_price[i] < typical_price[i-1]:
                negative_flow[i] = money_flow[i]
        mfi = np.zeros_like(closes)
        for i in range(period, len(closes)):
            pos_sum = np.sum(positive_flow[i-period+1:i+1])
            neg_sum = np.sum(negative_flow[i-period+1:i+1])
            mfi[i] = 100 if neg_sum == 0 else 100 - (100 / (1 + (pos_sum / neg_sum)))
        return mfi

    def _calculate_adx(self, highs, lows, closes, period=14):
        plus_dm = np.maximum(np.diff(highs), 0)
        minus_dm = np.maximum(np.diff(-lows), 0)
        tr = np.maximum(highs[1:] - lows[1:], np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
        atr = np.convolve(tr, np.ones(period)/period, mode='valid')
        plus_di = 100 * np.convolve(plus_dm, np.ones(period)/period, mode='valid') / (atr + 1e-9)
        minus_di = 100 * np.convolve(minus_dm, np.ones(period)/period, mode='valid') / (atr + 1e-9)
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
        adx = np.convolve(dx, np.ones(period)/period, mode='valid')
        return np.pad(adx, (len(closes) - len(adx), 0), 'edge')
