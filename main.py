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

bot_running = False
active_position = None
max_profit_reached = 0.0
account_balance = 0.00
closed_trades = []
scanned_pairs_data = {}
last_scan_status = "A aguardar início..."

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    global account_balance
    current_conf = config.load_config()
    
    if exchange_mgr.exchange:
        try:
            balance_data = await exchange_mgr.exchange.fetch_balance()
            account_balance = balance_data['USDT']['free'] if 'USDT' in balance_data else 0.0
        except Exception:
            pass

    btn_color = "#ef4444" if bot_running else "#22c55e"
    btn_text = "STOP BOT" if bot_running else "START BOT"
    status_badge = "🟢 Sistema Ativo & A Operar" if bot_running else "🔴 Sistema em Pausa (OFF)"

    trades_html = ""
    if not closed_trades:
        trades_html = "<p style='color:#94a3b8; text-align:center;'>Nenhuma operação fechada ainda.</p>"
    else:
        for t in closed_trades:
            color = "#4ade80" if t['pnl_usdt'] >= 0 else "#f87171"
            trades_html += f"""
            <div style="background:#0f172a; padding:12px; border-radius:8px; margin-bottom:8px; border-left: 4px solid {color};">
                <b>{t['symbol']} ({t['side']})</b><br>
                Resultado: <span style="color:{color};">{t['pnl_usdt']:+.2f} USDT ({t['pnl_percent']:+.2f}%)</span><br>
                <small style="color:#94a3b8;">Capital Inicial: {t['capital']} USDT</small>
            </div>
            """

    scanned_html = ""
    promising_pair = "A calcular..."
    for sym, data in scanned_pairs_data.items():
        scanned_html += f"<div style='padding:8px; border-bottom:1px solid #334155;'><b>{sym}</b>: Preço {data['price']} | RSI: {data['rsi']:.1f}</div>"
        if data.get('promising'):
            promising_pair = sym

    html_content = f"""
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="15">
        <title>BotTrd Pro</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding-bottom: 90px; }}
            .top-bar {{ display: flex; justify-content: space-between; align-items: center; background: #1e293b; padding: 15px 20px; border-bottom: 1px solid #334155; position: sticky; top: 0; z-index: 100; }}
            .profit-left {{ font-size: 14px; font-weight: bold; color: #4ade80; }}
            .balance-right {{ font-size: 14px; background: #0f172a; padding: 6px 12px; border-radius: 20px; border: 1px solid #38bdf8; color: #38bdf8; }}
            
            .content {{ padding: 20px; max-width: 600px; margin: auto; }}
            .tab-content {{ display: none; }}
            .tab-content.active {{ display: block; }}
            
            .card {{ background: #1e293b; padding: 20px; border-radius: 12px; margin-bottom: 15px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); border: 1px solid #334155; }}
            h2 {{ color: #38bdf8; font-size: 18px; margin-top: 0; }}
            .bot-title {{ font-size: 22px; font-weight: bold; color: #38bdf8; margin-bottom: 15px; display: flex; align-items: center; gap: 8px; }}
            
            .btn-toggle {{ width: 100%; padding: 14px; background: {btn_color}; color: white; border: none; font-size: 16px; font-weight: bold; border-radius: 8px; cursor: pointer; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.4); margin-bottom: 15px; }}
            
            /* Gráfico Profissional com Linha Divisora Long/Short */
            .pro-chart {{ background: #0f172a; height: 180px; border-radius: 8px; padding: 15px; border: 1px solid #334155; position: relative; display: flex; flex-direction: column; justify-content: space-between; }}
            .divider-line {{ position: absolute; top: 50%; left: 0; width: 100%; height: 2px; background: #facc15; z-index: 2; }}
            .divider-label {{ position: absolute; top: calc(50% - 10px); right: 10px; font-size: 10px; color: #facc15; background: #1e293b; padding: 2px 6px; border-radius: 4px; z-index: 3; }}
            .candles-container {{ display: flex; justify-content: space-around; align-items: flex-end; height: 100%; z-index: 1; }}
            .candle {{ width: 12px; background: #4ade80; border-radius: 2px; position: relative; }}
            .candle.down {{ background: #f87171; }}
            .wick {{ position: absolute; width: 2px; background: inherit; left: 5px; top: -6px; bottom: -6px; }}

            .bottom-nav {{ position: fixed; bottom: 0; left: 0; width: 100%; background: #1e293b; display: flex; justify-content: space-around; padding: 10px 0; border-top: 1px solid #334155; box-shadow: 0 -4px 15px rgba(0,0,0,0.5); z-index: 1000; }}
            .nav-item {{ background: none; border: none; color: #94a3b8; font-size: 12px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 4px; }}
            .nav-item.active {{ color: #38bdf8; font-weight: bold; }}
            .nav-item svg {{ width: 22px; height: 22px; fill: currentColor; }}

            input[type="text"], input[type="password"] {{ width: 100%; padding: 10px; margin-top: 5px; background: #0f172a; border: 1px solid #475569; color: white; border-radius: 6px; box-sizing: border-box; }}
            button[type="submit"] {{ width: 100%; margin-top: 15px; background: #0284c7; color: white; border: none; padding: 12px; font-size: 15px; border-radius: 6px; cursor: pointer; font-weight: bold; }}
        </style>
    </head>
    <body>

        <!-- Barra Superior -->
        <div class="top-bar">
            <div class="profit-left">Lucro: +0.00 USDT (0.00%)</div>
            <div class="balance-right">Saldo: {account_balance:.2f} USDT</div>
        </div>

        <div class="content">
            
            <!-- ABA 1: DASHBOARD -->
            <div id="tab-dashboard" class="tab-content">
                <div class="bot-title">⚡ BotTrd Pro</div>
                
                <form action="/toggle_bot" method="post">
                    <button type="submit" class="btn-toggle">{btn_text}</button>
                </form>
                <div style="text-align: center; font-size: 13px; margin-bottom: 15px; font-weight: bold;">{status_badge}</div>

                <div class="card">
                    <h2>📊 Visão Geral de Operações</h2>
                    <p><b>Estado:</b> {last_scan_status}</p>
                    <p><b>Par Promissor Atual:</b> <span style="color:#4ade80;">{promising_pair}</span></p>
                </div>

                <div class="card">
                    <h2>📈 Tendência de Alta / Baixa</h2>
                    <div class="pro-chart">
                        <div class="divider-line"></div>
                        <div class="divider-label">LONG / SHORT Line</div>
                        <div class="candles-container">
                            <div class="candle down" style="height: 40%;"><div class="wick"></div></div>
                            <div class="candle" style="height: 60%;"><div class="wick"></div></div>
                            <div class="candle down" style="height: 30%;"><div class="wick"></div></div>
                            <div class="candle" style="height: 75%;"><div class="wick"></div></div>
                            <div class="candle" style="height: 90%;"><div class="wick"></div></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- ABA 2: HISTÓRICO DE FECHADOS -->
            <div id="tab-historico" class="tab-content">
                <div class="bot-title">📜 Histórico</div>
                <div class="card">
                    <h2>Operações Fechadas</h2>
                    {trades_html}
                </div>
            </div>

            <!-- ABA 3: CONFIGURAÇÃO -->
            <div id="tab-config" class="tab-content">
                <div class="bot-title">⚙️ Configurações</div>
                <div class="card">
                    <h2>Parâmetros & API</h2>
                    <form action="/save" method="post">
                        <label>Bybit API Key:</label>
                        <input type="text" name="api_key" value="{current_conf['BYBIT_API_KEY']}" required>
                        
                        <label>Bybit API Secret:</label>
                        <input type="password" name="api_secret" value="{current_conf['BYBIT_API_SECRET']}" required>

                        <div style="margin-top: 15px; display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" name="is_testnet" value="true" {'checked' if current_conf['IS_TESTNET'] else ''}>
                            <label style="margin:0;">Ativar Testnet (Modo de Testes)</label>
                        </div>
                        
                        <button type="submit">Guardar Configurações</button>
                    </form>
                </div>
            </div>

            <!-- ABA 4: GRÁFICO & PARES ESCANEADOS -->
            <div id="tab-grafico" class="tab-content">
                <div class="bot-title">📊 Análise de Mercado</div>
                <div class="card">
                    <h2>🔍 Pares Escaneados</h2>
                    {scanned_html if scanned_html else "<p style='color:#94a3b8;'>A iniciar varredura de mercado...</p>"}
                </div>
                <div class="card">
                    <h2>🕯️ Velas Profissionais & Direção</h2>
                    <div class="pro-chart" style="height: 140px;">
                        <div class="divider-line"></div>
                        <div class="divider-label">Equilíbrio</div>
                        <div class="candles-container">
                            <div class="candle" style="height: 50%;"><div class="wick"></div></div>
                            <div class="candle down" style="height: 60%;"><div class="wick"></div></div>
                            <div class="candle" style="height: 80%;"><div class="wick"></div></div>
                        </div>
                    </div>
                </div>
            </div>

        </div>

        <!-- Abas Inferiores Flutuantes -->
        <div class="bottom-nav">
            <button class="nav-item" id="nav-dashboard" onclick="switchTab('dashboard')">
                <svg viewBox="0 0 24 24"><path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/></svg>
                Dashboard
            </button>
            <button class="nav-item" id="nav-historico" onclick="switchTab('historico')">
                <svg viewBox="0 0 24 24"><path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>
                Histórico
            </button>
            <button class="nav-item" id="nav-config" onclick="switchTab('config')">
                <svg viewBox="0 0 24 24"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>
                Configurações
            </button>
            <button class="nav-item" id="nav-grafico" onclick="switchTab('grafico')">
                <svg viewBox="0 0 24 24"><path d="M3.5 18.49l6-6.01 4 4L22 6.92l-1.41-1.41-7.09 7.97-4-4L2 16.99z"/></svg>
                Gráfico & Pares
            </button>
        </div>

        <script>
            function switchTab(tabId) {{
                document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
                
                document.getElementById('tab-' + tabId).classList.add('active');
                document.getElementById('nav-' + tabId).classList.add('active');
                
                localStorage.setItem('activeTab', tabId);
            }}

            window.onload = function() {{
                const savedTab = localStorage.getItem('activeTab') || 'dashboard';
                switchTab(savedTab);
            }};
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/toggle_bot", response_class=HTMLResponse)
async def toggle_bot():
    global bot_running
    bot_running = not bot_running
    return """
    <html>
    <meta http-equiv="refresh" content="0;url=/">
    <body></body>
    </html>
    """

@app.post("/save", response_class=HTMLResponse)
async def save_settings(api_key: str = Form(...), api_secret: str = Form(...), is_testnet: bool = Form(False)):
    config.save_config(api_key, api_secret, is_testnet)
    await exchange_mgr.update_credentials(api_key, api_secret, is_testnet)
    return """
    <html>
    <meta http-equiv="refresh" content="1;url=/">
    <body style="background:#0b0f19; color:white; font-family:Arial; text-align:center; padding-top:50px;">
        <h2 style="color:#4ade80;">Definições guardadas com sucesso!</h2>
        <p>A atualizar conexão com a Bybit...</p>
    </body>
    </html>
    """

async def trading_loop():
    global active_position, max_profit_reached, last_scan_status, scanned_pairs_data, closed_trades
    logging.info("Motor de trading iniciado.")
    while True:
        try:
            if not bot_running:
                last_scan_status = "Sistema em Pausa (clique em START BOT)."
                await asyncio.sleep(2)
                continue

            if not exchange_mgr.exchange:
                last_scan_status = "Aviso: Insira as chaves API na aba Configurações."
                await asyncio.sleep(5)
                continue

            if active_position:
                symbol = active_position['symbol']
                entry_price = active_position['entry_price']
                side = active_position['side']

                _, _, current_price, _ = await exchange_mgr.fetch_market_data(symbol)
                if current_price:
                    pnl_pct = (current_price - entry_price) / entry_price if side == 'LONG' else (entry_price - current_price) / entry_price
                    if pnl_pct > max_profit_reached:
                        max_profit_reached = pnl_pct

                    if trading_engine.evaluate_trailing_stop(pnl_pct, max_profit_reached):
                        logging.warning(f"Trailing Stop acionado em {symbol}. Fechando...")
                        await exchange_mgr.execute_market_order(symbol, 'SELL' if side == 'LONG' else 'BUY', active_position['amount'])
                        
                        pnl_usdt = active_position['capital'] * pnl_pct * 10 
                        closed_trades.insert(0, {
                            'symbol': symbol, 'side': side, 'pnl_usdt': pnl_usdt, 
                            'pnl_percent': pnl_pct * 100, 'capital': active_position['capital']
                        })
                        active_position = None
                        max_profit_reached = 0.0

            last_scan_status = "A escanear o mercado em tempo real..."
            tasks = [exchange_mgr.fetch_market_data(pair) for pair in config.PAIRS]
            results = await asyncio.gather(*tasks)

            scanned_pairs_data.clear()
            best_sig = None
            best_sym = None

            for symbol, ohlcv, current_price, _ in results:
                if not ohlcv:
                    continue
                indicators = trading_engine.calculate_indicators(ohlcv)
                sig = trading_engine.evaluate_signal(indicators)
                
                scanned_pairs_data[symbol] = {
                    'price': current_price,
                    'rsi': indicators['rsi'] if indicators else 50,
                    'promising': sig in ['LONG', 'SHORT']
                }

                if sig in ['LONG', 'SHORT'] and not active_position and bot_running:
                    best_sig = sig
                    best_sym = symbol

            if best_sig and best_sym:
                logging.info(f"Oportunidade detetada: {best_sig} em {best_sym}")
                capital_allocated = 50.0  
                order = await exchange_mgr.execute_market_order(best_sym, best_sig, 0.01)
                if order:
                    active_position = {
                        'symbol': best_sym, 'side': best_sig, 
                        'entry_price': scanned_pairs_data[best_sym]['price'], 
                        'amount': 0.01, 'capital': capital_allocated
                    }
                    max_profit_reached = 0.0

            last_scan_status = f"Escaneados {len(scanned_pairs_data)} pares com sucesso."

        except Exception as e:
            last_scan_status = f"Erro: {str(e)}"
            logging.error(f"Erro no loop: {e}")

        await asyncio.sleep(config.SCAN_INTERVAL)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(trading_loop())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
