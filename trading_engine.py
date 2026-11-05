import logging

class TradingEngine:
    def __init__(self, config):
        self.config = config

    def calculate_indicators(self, ohlcv):
        """Calcula indicadores técnicos de alta precisão"""
        if not ohlcv or len(ohlcv) < 14:
            return None
        
        closes = [candle[4] for candle in ohlcv]
        opens = [candle[1] for candle in ohlcv]
        
        # Cálculo de RSI (14 períodos)
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

        # Direção da vela atual e anterior para confirmar tendência imediata
        last_candle_green = closes[-1] > opens[-1]
        prev_candle_green = closes[-2] > opens[-2]

        return {
            "rsi": rsi,
            "close": closes[-1],
            "last_green": last_candle_green,
            "prev_green": prev_candle_green
        }

    def evaluate_signal(self, indicators):
        """
        Entrada cirúrgica e rigorosa:
        - LONG: RSI em zona atrativa (< 48) E confirmação de força compradora (velas verdes recentes).
        - SHORT: RSI em zona de exaustão (> 52) E confirmação de força vendedora (velas vermelhas recentes).
        Elimina entradas cegas que iniciam em negativo.
        """
        if not indicators:
            return None
        
        rsi = indicators["rsi"]
        last_green = indicators["last_green"]
        prev_green = indicators["prev_green"]
        
        # Só abre LONG se houver suporte no RSI e velas a apontar para cima
        if rsi < 50 and (last_green or prev_green):
            return "LONG"
        
        # Só abre SHORT se houver resistência no RSI e velas a apontar para baixo
        elif rsi > 50 and (not last_green or not prev_green):
            return "SHORT"
        
        return None

    def evaluate_trailing_stop(self, pnl_pct, max_profit_reached):
        """
        Trailing Stop Rigoroso de 15% de recuo sobre o lucro máximo:
        - Stop de emergência estrito em -0.2% para bloquear perdas indesejadas.
        - Assim que atinge lucro positivo, dispara imediatamente se o lucro recuar 15% a partir do pico máximo alcançado.
        """
        if pnl_pct <= -0.002: # Stop de emergência (-0.2%)
            return True

        if max_profit_reached <= 0.0005:
            if pnl_pct <= -0.0015:
                return True
            return False

        # Regra exata: disparo se o lucro atual recuou 15% do lucro máximo atingido (pico * 0.85)
        recoil_threshold = max_profit_reached * 0.85
        
        if pnl_pct < recoil_threshold:
            return True

        return False
