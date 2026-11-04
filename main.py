import asyncio
import logging
import time
import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
import config
from exchange_management import BybitExchangeManager
from trading_engine import TradingEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI()
exchange_mgr = BybitExchangeManager(config.BYBIT_API_KEY, config.BYBIT_API_SECRET, config.IS_TESTNET)
trading_engine = TradingEngine(config)

active_position = None
max_profit_reached = 0.0

# ==========================================
# ABA DE CONFIGURAÇÃO (PAINEL WEB)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def config_page(request: Request):
    current_conf = config.load_config()
    html_content = f"""
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <title>BotTrd - Painel de Configuração</title>
        <style>
            body {{ font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; }}
            .container {{ max-width: 500px; margin: auto; background: #1e293b; padding: 30px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }}
            h2 {{ color: #38bdf8; text-align: center; }}
            label {{ display: block; margin-top: 15px; font-weight: bold; }}
            input[type="text"], input[type="password"] {{ width: 100%; padding: 10px; margin-top: 5px; background: #0f172a; border: 1px solid #475569; color: white; border-radius: 5px; }}
            .checkbox-group {{ margin-top: 20px; display: flex; align-items: center; gap: 10px; }}
            button {{ width: 100%; margin-top: 25px; background: #0284c7; color: white; border: none; padding: 12px; font-size: 16px; border-radius: 5px; cursor: pointer; }}
            button:hover {{ background: #0369a1; }}
            .status {{ margin-top: 20px; text-align: center; font-size: 14px; color: #4ade80; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>BotTrd - Configuração de API</h2>
            <form action="/save" method="post">
                <label>Bybit API Key:</label>
                <input type="text" name="api_key" value="{current_conf['BYBIT_API_KEY']}" required>
                
                <label>Bybit API Secret:</label>
                <input type="password" name="api_secret" value="{current_conf['BYBIT_API_SECRET']}" required>
                
                <div class="checkbox-group">
                    <input type="checkbox" name="is_testnet" value="true" {'checked' if current_conf['IS_TESTNET'] else ''}>
                    <label style="margin:0;">Ativar Testnet (Modo de Testes)</label>
                </div>
                
                <button type="submit">Guardar e Reiniciar Conexão</button>
            </form>
            <div class="status">Estado do Robô: A Executar Operações 24/7</div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/save", response_class=HTMLResponse)
async def save_settings(api_key: str = Form(...), api_secret: str = Form(...), is_testnet: bool = Form(False)):
    config.save_config(api_key, api_secret, is_testnet)
    await exchange_mgr.update_credentials(api_key, api_secret, is_testnet)
    return """
    <html>
    <body style="background:#0f172a; color:white; font-family:Arial; text-align:center; padding-top:50px;">
        <h2 style="color:#4ade80;">Configurações guardadas com sucesso!</h2>
        <p>As novas chaves da Bybit foram aplicadas em tempo real.</p>
        <a href="/" style="color:#38bdf8; text-decoration:none; font-size:18px;">← Voltar ao Painel</a>
    </body>
    </html>
    """

# ==========================================
# MOTOR DE TRADING EM BACKGROUND
# ==========================================
async def trading_loop():
    global active_position, max_profit_reached
    logging.info("Motor de trading iniciado em segundo plano.")
    while True:
        try:
            if not exchange_mgr.exchange:
                logging.warning("Aviso: Chaves da Bybit ainda não configuradas. Visite a aba de configuração no site.")
                await asyncio.sleep(10)
                continue

            # 1. Gestão de Posição Ativa
            if active_position:
                symbol = active_position['symbol']
                entry_price = active_position['entry_price']
                side = active_position['side']

                _, _, current_price, _ = await exchange_mgr.fetch_market_data(symbol)
                if current_price:
                    pnl_percent = (current_price - entry_price) / entry_price if side == 'LONG' else (entry_price - current_price) / entry_price
                    if pnl_percent > max_profit_reached:
                        max_profit_reached = pnl_percent

                    if trading_engine.evaluate_trailing_stop(pnl_percent, max_profit_reached):
                        logging.warning(f"Trailing Stop acionado em {symbol}. Fechando...")
                        await exchange_mgr.execute_market_order(symbol, 'SELL' if side == 'LONG' else 'BUY', active_position['amount'])
                        active_position = None
                        max_profit_reached = 0.0

            # 2. Varredura de Mercado
            tasks = [exchange_mgr.fetch_market_data(pair) for pair in config.PAIRS]
            results = await asyncio.gather(*tasks)

            for symbol, ohlcv, current_price, _ in results:
                if not ohlcv:
                    continue
                indicators = trading_engine.calculate_indicators(ohlcv)
                signal = trading_engine.evaluate_signal(indicators)

                if signal in ['LONG', 'SHORT'] and not active_position:
                    logging.info(f"Sinal detetado: {signal} em {symbol}")
                    amount = 0.01 if 'BTC' in symbol else 0.1
                    order = await exchange_mgr.execute_market_order(symbol, signal, amount)
                    if order:
                        active_position = {'symbol': symbol, 'side': signal, 'entry_price': current_price, 'amount': amount}
                        max_profit_reached = 0.0
                    break

        except Exception as e:
            logging.error(f"Erro no ciclo de trading: {e}")

        await asyncio.sleep(config.SCAN_INTERVAL)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(trading_loop())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
