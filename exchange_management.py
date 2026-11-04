import ccxt.async_support as ccxt
import asyncio
import logging
import time

class BybitExchangeManager:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.exchange = None
        if self.api_key and self.api_secret:
            self._init_exchange()

    def _init_exchange(self):
        self.exchange = ccxt.bybit({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'linear'}
        })
        if self.testnet:
            self.exchange.set_sandbox_mode(True)
        logging.info("BybitExchangeManager inicializado com chaves dinâmicas.")

    async def update_credentials(self, api_key, api_secret, testnet):
        """Permite atualizar as chaves em tempo real sem reiniciar o bot."""
        if self.exchange:
            await self.exchange.close()
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self._init_exchange()

    async def fetch_market_data(self, symbol: str, timeframe: str = '5m', limit: int = 50):
        if not self.exchange:
            return symbol, None, None, 0.0
        start_time = time.time()
        try:
            ohlcv, ticker = await asyncio.gather(
                self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit),
                self.exchange.fetch_ticker(symbol)
            )
            latency = (time.time() - start_time) * 1000
            return symbol, ohlcv, ticker['last'], latency
        except Exception as e:
            logging.error(f"Erro ao obter dados para {symbol}: {e}")
            return symbol, None, None, 0.0

    async def execute_market_order(self, symbol: str, side: str, amount: float):
        if not self.exchange:
            return None
        try:
            order_side = 'buy' if side.upper() == 'LONG' else 'sell'
            return await self.exchange.create_order(symbol, 'market', order_side, amount)
        except Exception as e:
            logging.error(f"Erro ao executar ordem em {symbol}: {e}")
            return None

    async def close(self):
        if self.exchange:
            await self.exchange.close()
