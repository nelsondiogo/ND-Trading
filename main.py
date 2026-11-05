import asyncio
import logging
import os
import time
import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
import config
from exchange_management import BybitExchangeManager
from trading_engine import TradingEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI()

exchange_mgr = None
trading_engine = None

try:
    exchange_mgr = BybitExchangeManager(config.BYBIT_API_KEY, config.BYBIT_API_SECRET, config.IS_TESTNET)
    trading_engine = TradingEngine(config)
except Exception as e:
    logging.error(f"Erro ao inicializar módulos: {e}")

bot_running = False
active_position = None
max_profit_reached = 0.0
initial_account_balance = 0.0
current_account_balance = 0.0
total_realized_pnl = 0.0
closed_trades = []
scanned_pairs_data = {}
scan_latency_ms = 0.0
last_signal_text = "Nenhum sinal recente"
last_api_error = "Sincronizado com a Bybit com sucesso!"

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    global current_account_balance, initial_account_balance, last_api_error
    current_conf = config.load_config()
    current_leverage = current_conf.get("LEVERAGE", 10)
    
    if exchange_mgr and exchange_mgr.exchange:
        try:
            balance_data = {}
            try:
                balance_data = await exchange_mgr.exchange.fetch_balance({'type': 'linear'})
            except Exception:
                try:
                    balance_data = await exchange_mgr.exchange.fetch_balance({'accountType': 'UNIFIED'})
                except Exception:
                    balance_data = await exchange_mgr.exchange.fetch_balance()

            if balance_data and 'USDT' in balance_data:
                usdt_info = balance_data.get('USDT', {})
                live_bal = float(usdt_info.get('free', 0.0) or usdt_info.get('total', 0.0) or 0.0)
                
                if live_bal == 0.0 and 'info' in balance_data:
                    result_list = balance_data['info'].get('result', {}).get('list', [])
                    for acc in result_list:
                        for coin in acc.get('coin', []):
                            if coin.get('coin') == 'USDT':
                                live_bal = float(coin.get('walletBalance', 0.0) or coin.get('free', 0.0) or 0.0)

                if not bot_running:
                    initial_account_balance = live_bal
                    current_account_balance = live_bal
                else:
                    floating_pnl_usdt = 0.0
                    if active_position:
                        curr_p = active_position.get('current_price', active_position['entry_price'])
                        entry_p = active_position['entry_price']
                        amt = active_position['amount']
                        if active_position['side'] == 'LONG':
                            floating_pnl_usdt = (curr_p - entry_p) * amt
                        else:
                            floating_pnl_usdt = (entry_p - curr_p) * amt
                    current_account_balance = initial_account_balance + total_realized_pnl + floating_pnl_usdt
        except Exception as e:
            logging.error(f"Erro ao ler saldo: {e}")

    status_str = "OPERANDO" if bot_running else "PARADO"
    status_color = "#4ade80" if bot_running else "#f87171"
    multiplied_balance = current_account_balance * current_leverage

    active_card_html = "<div style='color:#94a3b8; text-align:center; padding:15px;'>Nenhuma posição ativa no momento.</div>"
    if active_position:
        side_color = "#f87171" if active_position['side'] == 'SHORT' else "#4ade80"
        curr_p = active_position.get('current_price', active_position['entry_price'])
        entry_p = active_position['entry_price']
        high_p = active_position.get('highest_price', entry_p)
        low_p = active_position.get('lowest_price', entry_p)
        pnl_unr = active_position.get('pnl_unrealized', 0.0)
        pnl_color = "#4ade80" if pnl_unr >= 0 else "#f87171"
        
        history_prices = active_position.get('price_history', [entry_p])
        min_h = min(history_prices)
        max_h = max(history_prices)
        spread = max_h - min_h if max_h != min_h else 0.0001
        
        svg_points = ""
        width = 300
        height = 60
        step = width / max(1, len(history_prices) - 1)
        
        for idx, p in enumerate(history_prices):
            x = idx * step
            y = height - ((p - min_h) / spread) * (height - 10) - 5
            svg_points += f"{x},{y} "

        active_card_html = f"""
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <b style="font-size:16px;">{active_position['symbol']}</b>
            <span style="background:{side_color}22; color:{side_color}; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold;">{active_position['side']} ({current_leverage}x)</span>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:10px;">
            <div>Preço Atual: <b style="color:{pnl_color};">+{curr_p:.5f}</b></div>
            <div>PNL N.Realiz.: <b style="color:{pnl_color};">{pnl_unr:+.2f}%</b></div>
        </div>
        <div style="background:#0b0f19; border-radius:6px; padding:6px; margin-bottom:10px; border:1px solid #2a374a;">
            <svg width="100%" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" style="overflow:visible;">
                <polyline fill="none" stroke="{pnl_color}" stroke-width="2" points="{svg_points}"/>
            </svg>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:5px; font-size:11px; text-align:center; color:#94a3b8;">
            <div style="background:#0b0f19; padding:4px; border-radius:4px;">ENTRADA<br><b style="color:#facc15;">+{entry_p:.5f}</b></div>
            <div style="background:#0b0f19; padding:4px; border-radius:4px;">MÁXIMO<br><b style="color:#4ade80;">+{high_p:.5f}</b></div>
            <div style="background:#0b0f19; padding:4px; border-radius:4px;">MÍNIMO<br><b style="color:#f87171;">+{low_p:.5f}</b></div>
        </div>
        """

    mercado_html = ""
    for sym, data in scanned_pairs_data.items():
        tag_color = "#f87171" if data['signal'] == 'SHORT' else "#4ade80"
        mercado_html += f"""
        <div style="background:#161f31; padding:12px; border-radius:8px; margin-bottom:8px; border:1px solid #2a374a;">
            <span style="background:{tag_color}22; color:{tag_color}; padding:2px 6px; border-radius:4px; font-size:11px; font-weight:bold;">{data['signal']}</span>
            <b style="font-size:14px; margin-left:8px;">{sym}</b>
            <div style="font-size:12px; color:#94a3b8; margin-top:4px;">Preço: {data['price']} | RSI: {data['rsi']:.1f}</div>
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
            <div style="background:#161f31; padding:12px; border-radius:8px; margin-bottom:8px; border:1px solid #2a374a;">
                <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px;">
                    <b>{t['symbol']} ({t['side']})</b>
                    <span style="color:{color}; font-weight:bold;">{t['pnl_usdt']:+.6f} USDT</span>
                </div>
                <small style="color:#94a3b8;">Fechado com sucesso</small>
            </div>
            """
    win_rate = int((wins / len(closed_trades)) * 100) if closed_trades else 0

    html_content = f"""
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>nd-bot v8</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding-bottom: 80px; }}
            .brand-bar {{ background: #0b0f19; text-align: center; padding: 6px; border-bottom: 1px solid #1e293b; font-size: 12px; color: #4ade80; }}
            .top-header {{ display: flex; justify-content: space-between; padding: 10px 15px; background: #0b0f19; border-bottom: 1px solid #1e293b; }}
            .top-card {{ background: #161f31; border: 1px solid #2a374a; padding: 8px; border-radius: 8px; text-align: center; width: 46%; }}
            .content {{ padding: 15px; max-width: 600px; margin: auto; }}
            .tab-content {{ display: none; }}
            .tab-content.active {{ display: block; }}
            .card {{ background: #161f31; border: 1px solid #2a374a; padding: 15px; border-radius: 10px; margin-bottom: 12px; }}
            .bottom-nav {{ position: fixed; bottom: 0; left: 0; width: 100%; background: #121824; display: flex; justify-content: space-around; padding: 10px 0; border-top: 1px solid #2a374a; z-index: 1000; }}
            .nav-item {{ background: none; border: none; color: #94a3b8; font-size: 11px; cursor: pointer; display: flex; flex-direction: column; align-items: center; }}
            .nav-item.active {{ color: #4ade80; font-weight: bold; }}
            input[type="text"], input[type="password"], input[type="number"] {{ width: 100%; padding: 10px; margin-top: 5px; background: #0b0f19; border: 1px solid #2a374a; color: white; border-radius: 6px; box-sizing: border-box; }}
            button[type="submit"] {{ width: 100%; margin-top: 15px; background: #0284c7; color: white; border: none; padding: 12px; border-radius: 6px; font-weight: bold; cursor: pointer; }}
        </style>
    </head>
    <body>
        <div class="brand-bar">nd-bot v8</div>
        <div class="top-header">
            <div class="top-card"><span style="font-size:10px; color:#94a3b8;">INICIAL</span><br><b style="color:#4ade80;">+{initial_account_balance:.6f}</b></div>
            <div class="top-card"><span style="font-size:10px; color:#94a3b8;">ATUAL</span><br><b style="color:#4ade80;">+{current_account_balance:.6f}</b></div>
        </div>
        <div class="content">
            <div id="tab-dashboard" class="tab-content">
                <div class="card">{active_card_html}</div>
                <div class="card" style="border-left: 4px solid #38bdf8;">
                    <span style="font-size:12px; color:#94a3b8;">ALAVANCAGEM MANUAL: <b>{current_leverage}x</b></span><br>
                    <span style="font-size:13px;">Poder de Compra: <b style="color:#38bdf8;">+{multiplied_balance:.6f} USDT</b></span>
                </div>
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
                    <div class="card" style="margin-bottom:0;"><span style="font-size:11px; color:#94a3b8;">STATUS</span><br><b style="color:{status_color};">{status_str}</b></div>
                    <div class="card" style="margin-bottom:0;"><span style="font-size:11px; color:#94a3b8;">PNL REALIZADO</span><br><b style="color:#4ade80;">++{total_realized_pnl:.6f}</b></div>
                </div>
                <div class="card" style="border-left: 4px solid #4ade80; background:#16241f;">
                    <span style="font-size:11px; color:#4ade80; font-weight:bold;">ESTADO / LOG DA API:</span><br>
                    <span style="font-size:12px; color:#f8fafc; word-break: break-all;">{last_api_error}</span>
                </div>
                <form action="/toggle_bot" method="post">
                    <button type="submit" style="background:{('#ef4444' if bot_running else '#22c55e')};">{('PARAR ROBÔ' if bot_running else 'INICIAR ROBÔ')}</button>
                </form>
            </div>
            
            <div id="tab-mercado" class="tab-content">
                <div style="font-size:12px; color:#94a3b8; margin-bottom:10px;">MERCADO DINÂMICO (10 PARES HFT)</div>
                {mercado_html if mercado_html else "<p style='color:#94a3b8; text-align:center;'>A varrer mercado...</p>"}
            </div>

            <div id="tab-historico" class="tab-content">
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
                    <div class="card" style="margin-bottom:0; text-align:center;"><span style="font-size:11px; color:#94a3b8;">LUCRO TOTAL</span><br><b style="color:#4ade80; font-size:15px;">+{total_realized_pnl:.6f}</b></div>
                    <div class="card" style="margin-bottom:0; text-align:center;"><span style="font-size:11px; color:#94a3b8;">WIN RATE</span><br><b style="color:#4ade80; font-size:15px;">{win_rate}%</b></div>
                </div>
                <div class="card">
                    <span style="font-size:12px; color:#94a3b8; font-weight:bold; display:block; margin-bottom:8px;">REGISTO DE TRADES ({len(closed_trades)})</span>
                    {trades_html}
                </div>
            </div>

            <div id="tab-ajustes" class="tab-content">
                <div class="card">
                    <h2 style="color:#38bdf8; font-size:16px; margin-top:0;">Configuração & Alavancagem</h2>
                    <form action="/save" method="post">
                        <label style="font-size:12px; color:#94a3b8;">Bybit API Key:</label>
                        <input type="text" name="api_key" value="{current_conf['BYBIT_API_KEY']}" required>
                        <label style="font-size:12px; color:#94a3b8; margin-top:8px; display:block;">Bybit API Secret:</label>
                        <input type="password" name="api_secret" value="{current_conf['BYBIT_API_SECRET']}" required>
                        <label style="font-size:12px; color:#94a3b8; margin-top:8px; display:block;">Alavancagem Manual:</label>
                        <input type="number" name="leverage" value="{current_leverage}" min="1" max="100" required>
                        <div style="margin-top: 12px; display: flex; align-items: center; gap: 8px;">
                            <input type="checkbox" name="is_testnet" value="true" {'checked' if current_conf['IS_TESTNET'] else ''}>
                            <label style="font-size:13px; margin:0;">Ativar Testnet</label>
                        </div>
                        <button type="submit">Guardar Definições</button>
                    </form>
                </div>
            </div>
        </div>

        <div class="bottom-nav">
            <button class="nav-item active" id="nav-dashboard" onclick="switchTab('dashboard')">Dashboard</button>
            <button class="nav-item" id="nav-mercado" onclick="switchTab('mercado')">Mercado</button>
            <button class="nav-item" id="nav-historico" onclick="switchTab('historico')">Histórico</button>
            <button class="nav-item" id="nav-ajustes" onclick="switchTab('ajustes')">Ajustes</button>
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
async def save_settings(api_key: str = Form(...), api_secret: str = Form(...), leverage: int = Form(10), is_testnet: bool = Form(False)):
    config.save_config(api_key, api_secret, is_testnet, leverage)
    if exchange_mgr:
        await exchange_mgr.update_credentials(api_key, api_secret, is_testnet)
    return """
    <html>
    <meta http-equiv="refresh" content="1;url=/">
    <body style="background:#0b0f19; color:white; font-family:Arial; text-align:center; padding-top:50px;">
        <h2 style="color:#4ade80;">Definições guardadas!</h2>
    </body>
    </html>
    """

async def trading_loop():
    global active_position, max_profit_reached, scanned_pairs_data, closed_trades, scan_latency_ms, last_signal_text, total_realized_pnl, last_api_error
    while True:
        try:
            if not exchange_mgr or not exchange_mgr.exchange:
                await asyncio.sleep(3)
                continue

            current_conf = config.load_config()
            leverage = current_conf.get("LEVERAGE", 10)

            # Sincronização direta do estado real da Bybit: verifica se a posição ainda existe na corretora
            if active_position and bot_running:
                try:
                    positions = await exchange_mgr.exchange.fetch_positions([active_position['symbol']])
                    real_pos_found = False
                    for p in positions:
                        if float(p.get('contracts', 0.0) or p.get('size', 0.0)) > 0:
                            real_pos_found = True
                            break
                    if not real_pos_found:
                        # Se a posição foi fechada externamente na Bybit, limpa o estado local
                        active_position = None
                        max_profit_reached = 0.0
                        last_api_error = "Posição detetada como fechada na Bybit."
                except Exception:
                    pass

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
                if not indicators:
                    continue
                sig = trading_engine.evaluate_signal(indicators)

                scanned_pairs_data[symbol] = {
                    'price': current_price,
                    'rsi': indicators['rsi'],
                    'signal': sig,
                    'score': 90
                }

                if sig in ['LONG', 'SHORT'] and not best_sym:
                    best_sig = sig
                    best_sym = symbol

            if active_position:
                symbol = active_position['symbol']
                entry_price = active_position['entry_price']
                side = active_position['side']
                curr_price = scanned_pairs_data.get(symbol, {}).get('price')

                if curr_price:
                    if curr_price > active_position['highest_price']:
                        active_position['highest_price'] = curr_price
                    if curr_price < active_position['lowest_price']:
                        active_position['lowest_price'] = curr_price

                    active_position['price_history'].append(curr_price)
                    if len(active_position['price_history']) > 20:
                        active_position['price_history'].pop(0)

                    pnl_pct = (curr_price - entry_price) / entry_price if side == 'LONG' else (entry_price - curr_price) / entry_price
                    active_position['current_price'] = curr_price
                    active_position['pnl_unrealized'] = pnl_pct * leverage * 100

                    if pnl_pct > max_profit_reached:
                        max_profit_reached = pnl_pct

                    should_close = trading_engine.evaluate_trailing_stop(pnl_pct, max_profit_reached)

                    if should_close and bot_running:
                        try:
                            await exchange_mgr.execute_market_order(symbol, 'SELL' if side == 'LONG' else 'BUY', active_position['amount'], leverage=leverage)
                            pnl_usdt = pnl_pct * active_position['amount'] * entry_price
                            total_realized_pnl += pnl_usdt
                            closed_trades.insert(0, {'symbol': symbol, 'side': side, 'pnl_usdt': pnl_usdt})
                            active_position = None
                            max_profit_reached = 0.0
                            last_api_error = f"Posição fechada com sucesso em {symbol}"
                        except Exception as e:
                            last_api_error = f"Erro ao fechar: {str(e)}"

            if best_sig and best_sym and bot_running and not active_position:
                last_signal_text = f"Enviando ordem {best_sig} em {best_sym}"
                curr_price = scanned_pairs_data[best_sym]['price']
                amount = 10.0 if 'DOGE' in best_sym else (1.0 if 'XRP' in best_sym else 1.0)

                try:
                    order = await exchange_mgr.execute_market_order(best_sym, best_sig, amount, leverage=leverage)
                    if order:
                        active_position = {
                            'symbol': best_sym, 'side': best_sig,
                            'entry_price': curr_price,
                            'current_price': curr_price,
                            'highest_price': curr_price,
                            'lowest_price': curr_price,
                            'price_history': [curr_price],
                            'amount': amount,
                            'pnl_unrealized': 0.0
                        }
                        max_profit_reached = 0.0
                        last_api_error = f"Ordem ABERTA com sucesso em {best_sym}!"
                except Exception as e:
                    last_api_error = f"ERRO BYBIT: {str(e)}"
                    logging.error(last_api_error)

        except Exception as e:
            last_api_error = f"Erro no loop: {str(e)}"
            logging.error(last_api_error)

        await asyncio.sleep(config.SCAN_INTERVAL)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(trading_loop())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
