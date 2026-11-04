import asyncio
import logging
import time
import os
from exchange_management import BybitExchangeManager
from trading_engine import TradingEngine

# Configuração de Logs otimizada com métrica de latência
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] Latência Scan: %(message)s")

class Config:
    BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "SUA_API_KEY")
    BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "SEU_API_SECRET")
    IS_TESTNET = os.getenv("IS_TESTNET", "true").lower() == "true"
    
    PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT"]
    SCAN_INTERVAL = 18  # Intervalo rigoroso de 15-20 segundos
    ADX_THRESHOLD = 25.0
    
    # Parâmetros de Trailing Stop Agressivo
    TRAILING_ACTIVATION_THRESHOLD = 0.01  # Ativa ao atingir +1%
    TRAILING_DRAWDOWN_PERCENT = 0.30      # Fecha se o lucro recuar 30% do pico

class BotOrchestrator:
    def __init__(self):
        self.config = Config()
        self.exchange = BybitExchangeManager(
            self.config.BYBIT_API_KEY, 
            self.config.BYBIT_API_SECRET, 
            self.config.IS_TESTNET
        )
        self.engine = TradingEngine(self.config)
        
        # Estado atual da posição (Zero hardcoded - puramente dinâmico via API)
        self.active_position = None
        self.max_profit_reached = 0.0

    async def monitor_and_manage_position(self):
        """Monitoriza a posição ativa em tempo real aplicando Trailing Stop avançado."""
        if not self.active_position:
            return

        symbol = self.active_position['symbol']
        entry_price = self.active_position['entry_price']
        side = self.active_position['side']

        _, _, current_price, _ = await self.exchange.fetch_market_data(symbol)
        if not current_price:
            return

        # Cálculo de PnL Percentual em tempo real
        if side == 'LONG':
            pnl_percent = (current_price - entry_price) / entry_price
        else:
            pnl_percent = (entry_price - current_price) / entry_price

        # Atualiza o pico de lucro máximo
        if pnl_percent > self.max_profit_reached:
            self.max_profit_reached = pnl_percent

        logging.info(f"[{symbol}] PnL Ativo: {pnl_percent*100:.2f}% | Pico Máximo: {self.max_profit_reached*100:.2f}%")

        # Verifica acionamento da Proteção de Reversão (Trailing Stop Agressivo)
        if self.engine.evaluate_trailing_stop(pnl_percent, self.max_profit_reached):
            logging.warning(f"Trailing Stop acionado em {symbol}! Fechando posição para garantir lucro.")
            await self.exchange.execute_market_order(symbol, 'SELL' if side == 'LONG' else 'BUY', self.active_position['amount'])
            self.active_position = None
            self.max_profit_reached = 0.0

    async def scan_market_cycle(self):
        """
        Arquitetura Assíncrona Paralela: Executa o scan de múltiplos pares simultaneamente
        e avalia a Oportunidade de Rotação de Capital.
        """
        start_time = time.time()
        
        # 1. Executa varredura paralela em todos os pares usando asyncio.gather
        tasks = [self.exchange.fetch_market_data(pair) for pair in self.config.PAIRS]
        results = await asyncio.gather(*tasks)
        
        scan_latency = (time.time() - start_time) * 1000
        logging.info(f"{scan_latency:.2f}ms | Escaneados {len(results)} pares em simultâneo.")

        best_new_signal = None
        best_symbol = None

        for symbol, ohlcv, current_price, _ in results:
            if not ohlcv:
                continue
            
            indicators = self.engine.calculate_indicators(ohlcv)
            signal = self.engine.evaluate_signal(indicators)

            if signal in ['LONG', 'SHORT']:
                best_new_signal = signal
                best_symbol = symbol
                break # Encontrou um sinal válido prioritário

        # 2. Dynamic Opportunity Cost Analysis (Rotação Inteligente de Capital)
        if best_new_signal and best_symbol:
            if self.active_position:
                # Se já tem posição, avalia se deve rotacionar
                curr_symbol = self.active_position['symbol']
                if curr_symbol != best_symbol:
                    _, _, curr_price, _ = await self.exchange.fetch_market_data(curr_symbol)
                    entry_p = self.active_position['entry_price']
                    is_long = self.active_position['side'] == 'LONG'
                    current_pnl = (curr_price - entry_p)/entry_p if is_long else (entry_p - curr_price)/entry_p
                    
                    # Se a posição atual estiver lucrativa, rotaciona o capital para o novo sinal estatisticamente superior
                    if current_pnl > 0.003: # Lucro superior a 0.3%
                        logging.info(f"Oportunidade superior em {best_symbol}. Rotacionando capital a fechar {curr_symbol} em lucro.")
                        await self.exchange.execute_market_order(curr_symbol, 'SELL' if is_long else 'BUY', self.active_position['amount'])
                        self.active_position = None
                        self.max_profit_reached = 0.0
            
            # Se o bot estiver livre, abre a nova posição imediatamente
            if not self.active_position:
                logging.info(f"Executando entrada {best_new_signal} em {best_symbol} com base nos filtros M5/H1/ADX.")
                amount = 0.01 if 'BTC' in best_symbol else 0.1
                order = await self.exchange.execute_market_order(best_symbol, best_new_signal, amount)
                if order:
                    _, _, execution_price, _ = await self.exchange.fetch_market_data(best_symbol)
                    self.active_position = {
                        'symbol': best_symbol,
                        'side': best_new_signal,
                        'entry_price': execution_price,
                        'amount': amount
                    }
                    self.max_profit_reached = 0.0

    async def run(self):
        """Loop principal contínuo rodando em background (ideal para Render Worker)."""
        logging.info("BotOrchestrator iniciado em modo autónomo 24/7.")
        while True:
            try:
                # O motor escaneia o mercado continuamente, mesmo com posição aberta
                await self.monitor_and_manage_position()
                await self.scan_market_cycle()
            except Exception as e:
                logging.error(f"Erro crítico no loop principal do bot: {e}")
            
            # Intervalo rigoroso de 15 a 20 segundos configurado
            await asyncio.sleep(self.config.SCAN_INTERVAL)

if __name__ == "__main__":
    orchestrator = BotOrchestrator()
    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        logging.info("Encerrando robô de trading de forma segura...")
