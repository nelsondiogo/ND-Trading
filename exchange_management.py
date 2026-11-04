import ccxt.async_support as ccxt
import logging
import time

class BybitExchangeManager:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.exchange = ccxt.bybit({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'linear', # Futuros Lineares USDT
            }
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)
        logging.info("BybitExchangeManager inicializado com sucesso.")

    async def fetch_market_data(self, symbol: str, timeframe: str = '5m', limit: int = 50):
        """Recupera dados OHLCV e ticker atual com medição de latência."""
        start_time = time.time()
        try:
            # Executa chamadas em paralelo para otimizar latência de rede
            ohlcv, ticker = await ccxt.async_support.asyncio.gather(
                self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit),
                self.exchange.fetch_ticker(symbol)
            )
            latency = (time.time() - start_time) * 1000  # em milissegundos
            return symbol, ohlcv, ticker['last'], latency
        except Exception as e:
            logging.error(f"Erro ao obter dados de mercado para {symbol}: {e}")
            return symbol, None, None, 0.0

    async def execute_market_order(self, symbol: str, side: str, amount: float):
        """Executa ordem a mercado ultra-rápida (Buy/Sell)."""
        try:
            order_side = 'buy' if side.upper() == 'LONG' else 'sell'
            order = await self.exchange.create_order(symbol, 'market', order_side, amount)
            logging.info(f"Ordem executada em {symbol}: {order_side.upper()} de {amount} unidades.")
            return order
        except Exception as e:
            logging.error(f"Falha na execução da ordem em {symbol}: {e}")
            return None

    async def close(self):
        await self.exchange.close()

