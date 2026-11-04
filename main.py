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
last_scan_status = "A aguardar início..."

# ==========================================
# PAINEL DE CONTROLO E DASHBOARD (UI)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    current_conf = config.load_config()
    has_keys = bool(current_conf['BYBIT_API_KEY'] and current_conf['BYBIT_API_SECRET'])
    
    status_color = "#4ade80" if has_keys and exchange_mgr.exchange else "#f87171"
    status_text = "Conectado à Bybit & A Operar" if has_keys and exchange_mgr.exchange else "Chaves em falta ou inválidas"

    pos_html = "Nenhuma posição aberta no momento."
    if active_position:
        pos_html = f"""
        <b>Ativo:</b> {active_position['symbol']}<br>
        <b>Lado:</b> {active_position['side']}<br>
        <b>Preço de Entrada:</b> {active_position['entry_price']}<br>
        <b>Pico de Lucro:</b> {max_profit_reached*100:.2f}%
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="15">
        <title>BotTrd - Dashboard de Trading</title>
        <style>
            body {{ font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }}
            .container {{ max-width: 600px; margin: auto; background: #1e293b; padding: 25px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }}
            h2 {{ color: #38bdf8; text-align: center; margin-bottom: 5px; }}
            .badge {{ text-align: center; font-size: 14px; color: {status_color}; margin-bottom: 20px; font-weight: bold; }}
            .card {{ background: #0f172a; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #334155; }}
            .card h3 {{ margin-top: 0; color: #38bdf8; font-size: 16px; }}
            label {{ display: block; margin-top: 10px; font-size: 14px; }}
            input[type="text"], input[type="password"] {{ width: 100%; padding: 8px; margin-top: 5px; background: #1e293b; border: 1px solid #475569; color: white; border-radius: 5px; box-sizing: border-box; }}
            .checkbox-group {{ margin-top: 15px; display: flex; align-items: center; gap: 10px; }}
            button {{ width: 100%; margin-top: 15px; background: #0284c7; color: white; border: none; padding: 10px; font-size: 15px; border-radius: 5px; cursor: pointer; }}
            button:hover {{ background: #0369a1; }}
            .footer-note {{ font-size: 12px; color: #94a3b8; text-align: center; margin-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>BotTrd Dashboard</h2>
            <div class="badge">● {status_text}</div>

            <div class="card">
                <h3>Estado do Motor de Mercado</h3>
                <p>{last_scan_status}</p>
            </div>

            <div class="card">
                <h3>Posição Ativa</h3>
                <p>{pos_html}</p>
            </div>

            <div class="card">
                <h3>Atualizar Credenciais da Bybit</h3>
                <form action="/save" method="post">
                    <label>Bybit API Key:</label>
                    <input type="text" name="api_key" value="{current_conf['BYBIT_API_KEY']}" required>
                    
                    <label>Bybit API Secret:</label>
                    <input type="password" name="api_secret" value="{current_conf['BYBIT_API_SECRET']}" required>
                    
                    <div class="checkbox-group">
                        <input type="checkbox" name="is_testnet" value="true" {'checked' if current_conf['IS_TESTNET'] else ''}>
                        <label style="margin:0;">Ativar Testnet (Modo de Testes)</label>
                    </div>
                    
                    <button type="submit">Guardar e Reconectar</button>
                </form>
            </div>
            <div class="footer-note">A página atualiza automaticamente a cada 15 segundos.</div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/save", response_class=HTMLResponse)
async def save_settings(api_key: str = Form(...), api_secret: str = Form(...), is_testnet: bool = Form(False)):
    config.save_config(api_key, api_secret, is_testnet)
    await exchange_mgr.update_credentials(api_key, api_secret, is_testnet)
    # Redireciona de volta para o painel principal após guardar
    return """
    <html>
    <meta http-equiv="refresh" content="1;url=/">
    <body style="background:#0f172a; color:white; font-family:Arial; text-align:center; padding-top:50px;">
        <h2 style="color:#4ade80;">Chaves atualizadas com sucesso!</h2>
        <p>A regressar ao painel principal...</p>
    </body>
    </html>
    """

# ==========================================
# MOTOR DE TRADING EM BACKGROUND
# ==========================================
async def trading_loop():
    global active_position, max_profit_reached, last_scan_status
    logging.info("Motor de trading iniciado em segundo plano.")
    while True:
        try:
            if not exchange_mgr.exchange:
                last_scan_status = "Aviso: Insira as chaves API válidas no painel abaixo."
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
            last_scan_status = "A escanear o mercado (BTC, ETH, SOL, BNB)..."
            tasks = [exchange_mgr.fetch_market_data(pair) for pair in config.PAIRS]
            results = await asyncio.gather(*tasks)

            valid_scans = 0
            for symbol, ohlcv, current_price, _ in results:
                if not ohlcv:
                    continue
                valid_scans += 1
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

            last_scan_status = f"Escaneados {valid_scans} pares com sucesso. À procura de oportunidades..."

        except Exception as e:
            last_scan_status = f"Erro no ciclo: {str(e)}"
            logging.error(f"Erro no ciclo de trading: {e}")

        await asyncio.sleep(config.SCAN_INTERVAL)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(trading_loop())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
