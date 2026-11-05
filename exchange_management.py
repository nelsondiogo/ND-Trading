import ccxt.async_support as ccxt
import logging

class BybitExchangeManager:
    def __init__(self, api_key, api_secret, is_testnet=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_testnet = is_testnet
        
        self.exchange = ccxt.bybit({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'linear',
            }
        })
        if self.is_testnet:
            self.exchange.set_sandbox_mode(True)

    async def set_leverage(self, symbol, leverage):
        try:
            await self.exchange.set_leverage(leverage, symbol)
        except Exception:
            pass

    async def fetch_market_data(self, symbol):
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe='1m', limit=60)
            ticker = await self.exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            return symbol, ohlcv, current_price, ticker
        except Exception as e:
            logging.error(f"Erro ao buscar dados de mercado para {symbol}: {e}")
            return symbol, [], 0.0, {}

    async def execute_market_order(self, symbol, side, amount, leverage=17, params=None):
        if params is None:
            params = {}
        try:
            await self.set_leverage(symbol, leverage)
            ccxt_side = side.lower()
            if ccxt_side not in ['buy', 'sell']:
                ccxt_side = 'buy' if side == 'LONG' else 'sell'
                
            order = await self.exchange.create_order(symbol, 'market', ccxt_side, amount, None, params)
            return order
        except Exception as e:
            logging.error(f"Erro ao executar ordem de mercado em {symbol}: {e}")
            raise e
