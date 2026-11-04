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
initial_account_balance = 0.0
current_account_balance = 0.0
total_realized_pnl = 0.0
closed_trades = []
scanned_pairs_data = {}
last_scan_status = "A aguardar início..."
scan_latency_ms = 0.0
last_signal_text = "Nenhum sinal recente"

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    global current_account_balance, initial_account_balance
    current_conf = config.load_config()
    
    # Leitura real do saldo da Bybit com tratamento robusto
    if exchange_mgr.exchange:
        try:
            balance_data = await exchange_mgr.exchange.fetch_balance()
            if 'info' in balance_data or 'USDT' in balance_data:
                usdt_info = balance_data.get('USDT', {})
                free_bal = float(usdt_info.get('free', 0.0) or usdt_info.get('total', 0.0) or 0.0)
                if initial_account_balance == 0.0 and free_bal > 0:
                    initial_account_balance = free_bal
                current_account_balance = free_bal
        except Exception as e:
            logging.error(f"Erro ao ler saldo da corretora: {e}")

    status_str = "OPERANDO" if bot_running else "PARADO"
    status_color = "#4ade80" if bot_running else "#f87171"

    active_card_html = "<div style='color:#94a3b8; text-align:center; padding:15px;'>Nenhuma posição ativa no momento.</div>"
    if active_position:
        side_color = "#f87171" if active_position['side'] == 'SHORT' else "#4ade80"
        active_card_html = f"""
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <b style="font-size:16px;">{active_position['symbol']}</b>
            <span style="background:{side_color}22; color:{side_color}; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold;">{active_position['side']}</span>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; font-size:13px; margin-bottom:12px;">
            <div><span style="color:#94a3b8; font-size:11px;">PNL N.REALIZ.</span><br><b style="color:{side_color};">{active_position.get('pnl_unrealized', 0.0):+.6f}</b></div>
            <div><span style="color:#94a3b8; font-size:11px;">PRECO</span><br><b>+{active_position.get('current_price', 0.0):.6f}</b></div>
            <div><span style="color:#94a3b8; font-size:11px;">ENTRADA</span><br><b style="color:#facc15;">+{active_position['entry_price']:.6f}</b></div>
            <div><span style="color:#94a3b8; font-size:11px;">PEAK / LOCK</span><br><b>{max_profit_reached*100:.2f}% / -</b></div>
        </div>
        """

    trades_html = ""
    wins = 0
    if not closed_trades:
        trades_html = "<p style='color:#94a3b8; text-align:center;'>Nenhuma operação fechada ainda.</p>"
    else:
        for t in closed_trades:
            if t['pnl_usdt'] >= 0:
                wins += 1
            color = "#4ade80" if t['pnl_usdt'] >= 0 else "#f87171"
            trades_html += f"""
            <div style="background:#161f31; padding:12px; border-radius:8px; margin-bottom:10px; border:1px solid #2a374a;">
                <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px;">
                    <b>{t['symbol']} ({t['side']})</b>
                    <span style="color:{color}; font-weight:bold;">{t['pnl_usdt']:+.6f}</span>
                </div>
                <small style="color:#94a3b8;">DRAWDOWN | peak={t.get('peak', 0)}%</small>
            </div>
            """
    win_rate = int((wins / len(closed_trades)) * 100) if closed_trades else 0

    mercado_html = ""
    for sym, data in scanned_pairs_data.items():
        tag_color = "#f87171" if data['signal'] == 'SHORT' else "#4ade80"
        mercado_html += f"""
        <div style="background:#161f31; padding:14px; border-radius:8px; margin-bottom:10px; border:1px solid #2a374a;">
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                <span style="background:{tag_color}22; color:{tag_color}; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold;">{data['signal']}</span>
                <b style="color:{tag_color};">{data.get('score', 80)}%</b>
            </div>
            <div style="font-size:15px; font-weight:bold; margin-bottom:6px;">{sym}</div>
            <div style="font-size:12px; color:#94a3b8;">Preço: {data['price']} | ADX:{data['adx']:.1f} RSI:{data['rsi']:.1f}</div>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="10">
        <title>nd-bot v8</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding-bottom: 90px; }}
            .brand-bar {{ background: #0b0f19; text-align: center; padding: 6px 0; border-bottom: 1px solid #1e293b; font-size: 12px; font-weight: 500; color: #4ade80; letter-spacing: 1px; }}
            .top-header {{ display: flex; justify-content: space-between; align-items: center; background: #0b0f19; padding: 10px 15px; border-bottom: 1px solid #1e293b; }}
            .top-card {{ background: #161f31; border: 1px solid #2a374a; padding: 8px 12px; border-radius: 8px; text-align: center; width: 46%; }}
            .top-card span {{ font-size: 10px; color: #94a3b8; font-weight: bold; display: block; }}
            .top-card b {{ font-size: 13px; }}
            .content {{ padding: 15px; max-width: 600px; margin: auto; }}
            .tab-content {{ display: none; }}
            .tab-content.active {{ display: block; }}
            .card {{ background: #161f31; border: 1px solid #2a374a; padding: 15px; border-radius: 10px; margin-bottom: 12px; }}
            .bottom-nav {{ position: fixed; bottom: 0; left: 0; width: 100%; background: #121824; display: flex; justify-content: space-around; padding: 10px 0; border-top: 1px solid #2a374a; z-index: 1000; }}
            .nav-item {{ background: none; border: none; color: #94a3b8; font-size: 11px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 4px; }}
            .nav-item.active {{ color: #4ade80; font-weight: bold; }}
            .nav-item svg {{ width: 20px; height: 20px; fill: currentColor; }}
            input[type="text"], input[type="password"] {{ width: 100%; padding: 10px; margin-top: 5px; background: #0b0f19; border: 1px solid #2a374a; color: white; border-radius: 6px; box-sizing: border-box; }}
            button[type="submit"] {{ width: 100%; margin-top: 15px; background: #0284c7; color: white; border: none; padding: 12px; font-size: 14px; border-radius: 6px; cursor: pointer; font-weight: bold; }}
        </style>
    </head>
    <body>

        <div class="brand-bar">nd-bot v8</div>

        <div class="top-header">
            <div class="top-card">
                <span>INICIAL</span>
                <b style="color:#4ade80;">+{initial_account_balance:.6f}</b>
            </div>
            <div class="top-card">
                <span>ATUAL</span>
                <b style="color:#4ade80;">+{current_account_balance:.6f}</b>
            </div>
        </div>

        <div class="content">
            
            <div id="tab-dashboard" class="tab-content">
                <div class="card">{active_card_html}</div>

                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:12px;">
                    <div class="card" style="margin-bottom:0;">
                        <span style="color:#94a3b8; font-size:11px;">STATUS</span>
                        <div style="font-size:15px; font-weight:bold; color:{status_color}; margin-top:4px;">{status_str}</div>
                    </div>
                    <div class="card" style="margin-bottom:0;">
                        <span style="color:#94a3b8; font-size:11px;">PNL REALIZADO</span>
                        <div style="font-size:15px; font-weight:bold; color:#4ade80; margin-top:4px;">++{total_realized_pnl:.6f}</div>
                    </div>
                </div>

                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:12px;">
                    <div class="card" style="margin-bottom:0;">
                        <span style="color:#94a3b8; font-size:11px;">ULTIMO SINAL</span>
                        <div style="font-size:12px; font-weight:bold; margin-top:4px;">{last_signal_text}</div>
                    </div>
                    <div class="card" style="margin-bottom:0;">
                        <span style="color:#94a3b8; font-size:11px;">LATENCIA SCAN</span>
                        <div style="font-size:14px; font-weight:bold; color:#f87171; margin-top:4px;">{scan_latency_ms:.1f}ms</div>
                    </div>
                </div>

                <div class="card">
                    <span style="color:#94a3b8; font-size:11px; display:block; margin-bottom:8px;">EVOLUCAO PNL (USDT)</span>
                    <div style="background:#0b0f19; height:110px; border-radius:6px; border:1px solid #2a374a;"></div>
                </div>

                <form action="/toggle_bot" method="post">
                    <button type="submit" style="background:{('#ef4444' if bot_running else '#22c55e')};">{('PARAR ROBÔ' if bot_running else 'INICIAR ROBÔ')}</button>
                </form>
            </div>

            <div id="tab-mercado" class="tab-content">
                <div style="font-size:12px; color:#94a3b8; margin-bottom:10px;">PARES ({len(scanned_pairs_data)}) | SCAN ATIVO</div>
                {mercado_html if mercado_html else "<p style='color:#94a3b8; text-align:center;'>A varrer mercado em tempo real...</p>"}
            </div>

            <div id="tab-grafico" class="tab-content">
                <div class="card">
                    <div style="font-size:12px; color:#38bdf8; font-weight:bold; margin-bottom:10px;">DOGEUSDT Perpetual Contract</div>
                    <div style="background:#0b0f19; height:240px; border-radius:8px; display:flex; align-items:center; justify-content:center; border:1px solid #2a374a; color:#94a3b8; font-size:13px;">
                        [Gráfico de Velas / TradingView]
                    </div>
                </div>
            </div>

            <div id="tab-historico" class="tab-content">
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:15px;">
                    <div class="card" style="margin-bottom:0; text-align:center;">
                        <span style="color:#94a3b8; font-size:11px;">LUCRO TOTAL</span>
                        <b style="color:#4ade80; font-size:16px;">+{total_realized_pnl:.6f}</b>
                    </div>
                    <div class="card" style="margin-bottom:0; text-align:center;">
                        <span style="color:#94a3b8; font-size:11px;">WIN RATE</span>
                        <b style="color:#4ade80; font-size:16px;">{win_rate}%</b>
                    </div>
                </div>
                <div class="card">
                    <span style="font-size:12px; color:#94a3b8; font-weight:bold; display:block; margin-bottom:10px;">TRADES ({len(closed_trades)})</span>
                    {trades_html}
                </div>
            </div>

            <div id="tab-ajustes" class="tab-content">
                <div class="card">
                    <h2 style="color:#38bdf8; font-size:16px; margin-top:0;">Configuração de API & Chaves</h2>
                    <form action="/save" method="post">
                        <label style="font-size:12px; color:#94a3b8;">Bybit API Key:</label>
                        <input type="text" name="api_key" value="{current_conf['BYBIT_API_KEY']}" required>
                        
                        <label style="font-size:12px; color:#94a3b8; margin-top:10px; display:block;">Bybit API Secret:</label>
                        <input type="password" name="api_secret" value="{current_conf['BYBIT_API_SECRET']}" required>

                        <div style="margin-top: 15px; display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" name="is_testnet" value="true" {'checked' if current_conf['IS_TESTNET'] else ''}>
                            <label style="margin:0; font-size:13px;">Ativar Testnet (Modo de Testes)</label>
                        </div>
                        
                        <button type="submit">Guardar Definições</button>
                    </form>
                </div>
            </div>

        </div>

        <div class="bottom-nav">
            <button class="nav-item" id="nav-dashboard" onclick="switchTab('dashboard')">
                <svg viewBox="0 0 24 24"><path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/></svg>
                Dashboard
            </button>
            <button class="nav-item" id="nav-mercado" onclick="switchTab('mercado')">
                <svg viewBox="0 0 24 24"><path d="M3.5 18.49l6-6.01 4 4L22 6.92l-1.41-1.41-7.09 7.97-4-4L2 16.99z"/></svg>
                Mercado
            </button>
            <button class="nav-item" id="nav-grafico" onclick="switchTab('grafico')">
                <svg viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z"/></svg>
                Grafico
            </button>
            <button class="nav-item" id="nav-historico" onclick="switchTab('historico')">
                <svg viewBox="0 0 24 24"><path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>
                Historico
            </button>
            <button class="nav-item" id="nav-ajustes" onclick="switchTab('ajustes')">
                <svg viewBox="0 0 24 24"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>
                Ajustes
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
    return """<html><meta http-equiv="refresh" content="0;url=/"><body></body></html>"""

@app.post("/save", response_class=HTMLResponse)
async def save_settings(api_key: str = Form(...), api_secret: str = Form(...), is_testnet: bool = Form(False)):
    config.save_config(api_key, api_secret, is_testnet)
    await exchange_mgr.update_credentials(api_key, api_secret, is_testnet)
    return """
    <html>
    <meta http-equiv="refresh" content="1;url=/">
    <body style="background:#0b0f19; color:white; font-family:Arial; text-align:center; padding-top:50px;">
        <h2 style="color:#4ade80;">Chaves atualizadas com sucesso!</h2>
        <p>A sincronizar com a Bybit...</p>
    </body>
    </html>
    """

async def trading_loop():
    global active_position, max_profit_reached, last_scan_status, scanned_pairs_data, closed_trades, scan_latency_ms, last_signal_text, total_realized_pnl
    logging.info("Motor de trading iniciado.")
    while True:
        try:
            if not exchange_mgr.exchange:
                await asyncio.sleep(3)
                continue

            t_start = time.time()
            tasks = [exchange_mgr.fetch_market_data(pair) for pair in config.PAIRS]
            results = await asyncio.gather(*tasks)
            scan_latency_ms = (time.time() - t_start) * 1000

            scanned_pairs_data.clear()
            best_sig = None
            best_sym = None

            for symbol, ohlcv, current_price, _ in results:
                if not ohlcv or not current_price:
                    continue
                indicators = trading_engine.calculate_indicators(ohlcv)
                sig = trading_engine.evaluate_signal(indicators)
                
                scanned_pairs_data[symbol] = {
                    'price': current_price,
                    'rsi': indicators['rsi'] if indicators else 50,
                    'adx': indicators['adx'] if indicators else 30,
                    'signal': sig if sig in ['LONG', 'SHORT'] else 'SHORT',
                    'score': 85 if sig != 'NEUTRAL' else 65
                }

                if sig in ['LONG', 'SHORT'] and not active_position and bot_running:
                    best_sig = sig
                    best_sym = symbol

            last_scan_status = f"Escaneados {len(scanned_pairs_data)} pares."

            if best_sig and best_sym and bot_running:
                last_signal_text = f"{best_sig} {best_sym}"
                amount = 10.0 if 'DOGE' in best_sym else 0.01
                order = await exchange_mgr.execute_market_order(best_sym, best_sig, amount)
                if order:
                    active_position = {
                        'symbol': best_sym, 'side': best_sig, 
                        'entry_price': scanned_pairs_data[best_sym]['price'], 
                        'amount': amount
                    }
                    max_profit_reached = 0.0

        except Exception as e:
            logging.error(f"Erro no ciclo de trading: {e}")

        await asyncio.sleep(config.SCAN_INTERVAL)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(trading_loop())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
