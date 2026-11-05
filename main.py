import asyncio
import logging
import os
import time
import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
import config
from exchange_management import BybitExchangeManager
from trading_engine import TradingEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI()

exchange_mgr = None
trading_engine = None

def init_exchange_manager():
    global exchange_mgr
    try:
        if config.BYBIT_API_KEY and config.BYBIT_API_SECRET:
            exchange_mgr = BybitExchangeManager(config.BYBIT_API_KEY, config.BYBIT_API_SECRET, config.IS_TESTNET)
            logging.info("Exchange manager inicializado com sucesso.")
        else:
            exchange_mgr = None
    except Exception as e:
        logging.error(f"Erro ao inicializar exchange manager: {e}")
        exchange_mgr = None

init_exchange_manager()
try:
    trading_engine = TradingEngine(config)
except Exception as e:
    logging.error(f"Erro ao inicializar trading engine: {e}")

bot_running = False
active_position = None
max_profit_reached = 0.0
initial_account_balance = 0.0
current_account_balance = 0.0
total_realized_pnl = 0.0
closed_trades = []
scanned_pairs_data = {}
last_api_error = "Sistema HFT estabilizado (DOGE, XRP, ADA)!"

async def fetch_live_balance():
    global initial_account_balance, current_account_balance
    if not exchange_mgr or not exchange_mgr.exchange:
        return 0.0
    try:
        balance_data = {}
        try:
            balance_data = await exchange_mgr.exchange.fetch_balance({'type': 'linear'})
        except Exception:
            try:
                balance_data = await exchange_mgr.exchange.fetch_balance({'accountType': 'UNIFIED'})
            except Exception:
                balance_data = await exchange_mgr.exchange.fetch_balance()

        live_bal = 0.0
        if balance_data:
            if 'USDT' in balance_data:
                usdt_info = balance_data.get('USDT', {})
                live_bal = float(usdt_info.get('free', 0.0) or usdt_info.get('total', 0.0) or 0.0)
            
            if live_bal == 0.0 and 'info' in balance_data:
                result_list = balance_data['info'].get('result', {}).get('list', [])
                for acc in result_list:
                    for coin in acc.get('coin', []):
                        if coin.get('coin') == 'USDT':
                            live_bal = float(coin.get('walletBalance', 0.0) or coin.get('free', 0.0) or coin.get('availableToWithdraw', 0.0) or 0.0)

        if live_bal > 0:
            if initial_account_balance == 0.0:
                initial_account_balance = live_bal
            
            current_conf = config.load_config()
            leverage = int(current_conf.get("LEVERAGE", 17))
            floating_pnl_usdt = 0.0
            if active_position:
                cp = active_position.get('current_price', active_position['entry_price'])
                ep = active_position['entry_price']
                amt = active_position['amount']
                if active_position['side'] == 'LONG':
                    floating_pnl_usdt = (cp - ep) * amt * (leverage / 10)
                else:
                    floating_pnl_usdt = (ep - cp) * amt * (leverage / 10)
            
            current_account_balance = initial_account_balance + floating_pnl_usdt
        return current_account_balance
    except Exception as e:
        logging.error(f"Erro ao ler saldo: {e}")
        return current_account_balance

@app.get("/api/state")
async def get_bot_state():
    await fetch_live_balance()
    current_conf = config.load_config()
    leverage = int(current_conf.get("LEVERAGE", 17))
    multiplied = current_account_balance * leverage
    wins = sum(1 for t in closed_trades if t['pnl_usdt'] >= 0)
    win_rate = int((wins / len(closed_trades)) * 100) if closed_trades else 0

    return {
        "bot_running": bot_running,
        "initial_balance": round(initial_account_balance, 6),
        "current_balance": round(current_account_balance, 6),
        "realized_pnl": round(total_realized_pnl, 6),
        "multiplied_balance": round(multiplied, 6),
        "leverage": leverage,
        "last_api_error": last_api_error,
        "active_position": active_position,
        "scanned_pairs": scanned_pairs_data,
        "closed_trades": closed_trades,
        "win_rate": win_rate
    }

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    current_conf = config.load_config()
    current_leverage = int(current_conf.get("LEVERAGE", 17))
    
    html_content = f"""<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>nd-bot v8</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding-bottom: 90px; }}
        .brand-bar {{ background: #0b0f19; text-align: center; padding: 6px; border-bottom: 1px solid #1e293b; font-size: 12px; color: #4ade80; }}
        .top-header {{ display: flex; justify-content: space-between; padding: 10px 15px; background: #0b0f19; border-bottom: 1px solid #1e293b; }}
        .top-card {{ background: #161f31; border: 1px solid #2a374a; padding: 8px; border-radius: 8px; text-align: center; width: 46%; }}
        .content {{ padding: 15px; max-width: 600px; margin: auto; }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        .card {{ background: #161f31; border: 1px solid #2a374a; padding: 15px; border-radius: 10px; margin-bottom: 12px; }}
        .bottom-nav {{ position: fixed; bottom: 0; left: 0; width: 100%; background: #121824; display: flex; justify-content: space-around; padding: 12px 0 16px 0; border-top: 1px solid #2a374a; z-index: 1000; }}
        .nav-item {{ background: none; border: none; color: #94a3b8; font-size: 12px; font-weight: bold; cursor: pointer; display: flex; flex-direction: column; align-items: center; }}
        .nav-item.active {{ color: #4ade80; font-weight: 800; }}
        input[type="text"], input[type="password"], input[type="number"] {{ width: 100%; padding: 10px; margin-top: 5px; background: #0b0f19; border: 1px solid #2a374a; color: white; border-radius: 6px; box-sizing: border-box; }}
        button[type="submit"] {{ width: 100%; margin-top: 15px; background: #0284c7; color: white; border: none; padding: 12px; border-radius: 6px; font-weight: bold; cursor: pointer; }}
    </style>
</head>
<body>
    <div class="brand-bar">nd-bot v8 (Saída por Inversão de Sinal & Stop Rigoroso)</div>
    <div class="top-header">
        <div class="top-card"><span style="font-size:10px; color:#94a3b8;">INICIAL</span><br><b id="lbl-initial" style="color:#4ade80;">0.000000</b></div>
        <div class="top-card"><span style="font-size:10px; color:#94a3b8;">ATUAL</span><br><b id="lbl-current" style="color:#4ade80;">0.000000</b></div>
    </div>
    <div class="content">
        <div id="tab-dashboard" class="tab-content active">
            <div class="card" id="active-position-card">
                <div style="color:#94a3b8; text-align:center; padding:15px;">Nenhuma posição ativa no momento.</div>
            </div>
            <div class="card" style="border-left: 4px solid #38bdf8;">
                <span style="font-size:12px; color:#94a3b8;">ALAVANCAGEM CONFIGURADA: <b id="lbl-lev" style="color:#4ade80;">{current_leverage}x</b></span><br>
                <span style="font-size:13px;">Poder de Compra: <b id="lbl-power" style="color:#38bdf8;">0.000000 USDT</b></span>
            </div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
                <div class="card" style="margin-bottom:0;"><span style="font-size:11px; color:#94a3b8;">STATUS</span><br><b id="lbl-status" style="color:#f87171;">PARADO</b></div>
                <div class="card" style="margin-bottom:0;"><span style="font-size:11px; color:#94a3b8;">PNL REALIZADO</span><br><b id="lbl-realized" style="color:#4ade80;">0.000000</b></div>
            </div>
            <div class="card" style="border-left: 4px solid #4ade80; background:#16241f;">
                <span style="font-size:11px; color:#4ade80; font-weight:bold;">ESTADO / LOG DA API:</span><br>
                <span id="lbl-log" style="font-size:12px; color:#f8fafc; word-break: break-all;">A aguardar início...</span>
            </div>
            <form action="/toggle_bot" method="post">
                <button type="submit" id="btn-toggle" style="background:#22c55e;">INICIAR ROBÔ</button>
            </form>
        </div>
        
        <div id="tab-mercado" class="tab-content">
            <div style="font-size:12px; color:#94a3b8; margin-bottom:10px;">MERCADO DINÂMICO</div>
            <div id="mercado-container"><p style="color:#94a3b8; text-align:center;">A varrer mercado...</p></div>
        </div>

        <div id="tab-historico" class="tab-content">
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
                <div class="card" style="margin-bottom:0; text-align:center;"><span style="font-size:11px; color:#94a3b8;">LUCRO TOTAL</span><br><b id="lbl-total-lucro" style="color:#4ade80; font-size:15px;">0.000000</b></div>
                <div class="card" style="margin-bottom:0; text-align:center;"><span style="font-size:11px; color:#94a3b8;">WIN RATE</span><br><b id="lbl-winrate" style="color:#4ade80; font-size:15px;">0%</b></div>
            </div>
            <div class="card">
                <span style="font-size:12px; color:#94a3b8; font-weight:bold; display:block; margin-bottom:8px;">REGISTO DE TRADES</span>
                <div id="historico-container"><p style="color:#94a3b8; text-align:center;">Nenhuma operação fechada ainda.</p></div>
            </div>
        </div>

        <div id="tab-ajustes" class="tab-content">
            <div class="card">
                <h2 style="color:#38bdf8; font-size:16px; margin-top:0;">Configuração & Alavancagem</h2>
                <form action="/save" method="post">
                    <label style="font-size:12px; color:#94a3b8;">Bybit API Key:</label>
                    <input type="text" name="api_key" value="{current_conf['BYBIT_API_KEY']}" placeholder="Insira a sua API Key" required>
                    <label style="font-size:12px; color:#94a3b8; margin-top:8px; display:block;">Bybit API Secret:</label>
                    <input type="password" name="api_secret" value="{current_conf['BYBIT_API_SECRET']}" placeholder="Insira o seu API Secret" required>
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
            setInterval(updateDashboardData, 2000);
        }};

        function cleanCoinName(symbol) {{
            if (!symbol) return '';
            return symbol.split('/')[0].toUpperCase();
        }}

        function formatColoredValue(val, decimals = 6) {{
            const num = Number(val) || 0;
            if (num < 0) {{
                return `<span style="color: #f87171;">-${{Math.abs(num).toFixed(decimals)}}</span>`;
            }} else if (num > 0) {{
                return `<span style="color: #4ade80;">+${{num.toFixed(decimals)}}</span>`;
            }} else {{
                return `<span style="color: #f8fafc;">0.${{'0'.repeat(decimals)}}</span>`;
            }}
        }}

        function formatColoredPct(val) {{
            const num = Number(val) || 0;
            if (num < 0) {{
                return `<span style="color: #f87171;">${{num.toFixed(2)}}%</span>`;
            }} else if (num > 0) {{
                return `<span style="color: #4ade80;">+${{num.toFixed(2)}}%</span>`;
            }} else {{
                return `<span style="color: #f8fafc;">0.00%</span>`;
            }}
        }}

        async function updateDashboardData() {{
            try {{
                const response = await fetch('/api/state');
                const data = await response.json();

                document.getElementById('lbl-initial').innerHTML = formatColoredValue(data.initial_balance);
                document.getElementById('lbl-current').innerHTML = formatColoredValue(data.current_balance);
                document.getElementById('lbl-realized').innerHTML = formatColoredValue(data.realized_pnl);
                document.getElementById('lbl-power').innerHTML = formatColoredValue(data.multiplied_balance) + ' USDT';
                document.getElementById('lbl-lev').innerText = data.leverage + 'x';
                document.getElementById('lbl-total-lucro').innerHTML = formatColoredValue(data.realized_pnl);
                document.getElementById('lbl-winrate').innerText = data.win_rate + '%';
                document.getElementById('lbl-log').innerText = data.last_api_error;

                const statusEl = document.getElementById('lbl-status');
                const btnToggle = document.getElementById('btn-toggle');
                if (data.bot_running) {{
                    statusEl.innerText = 'OPERANDO';
                    statusEl.style.color = '#4ade80';
                    btnToggle.innerText = 'PARAR ROBÔ';
                    btnToggle.style.background = '#ef4444';
                }} else {{
                    statusEl.innerText = 'PARADO';
                    statusEl.style.color = '#f87171';
                    btnToggle.innerText = 'INICIAR ROBÔ';
                    btnToggle.style.background = '#22c55e';
                }}

                const posCard = document.getElementById('active-position-card');
                if (data.active_position) {{
                    const pos = data.active_position;
                    const sideColor = pos.side === 'SHORT' ? '#f87171' : '#4ade80';
                    const cleanName = cleanCoinName(pos.symbol);
                    const pnlPct = pos.pnl_unrealized;
                    const pnlUsdt = (pnlPct / 100) * (pos.amount * pos.entry_price);
                    
                    posCard.innerHTML = `
                        <div style="margin-bottom:8px;">
                            <div style="font-size:22px; font-weight:900; color:#f8fafc; margin-bottom:4px;"><b>${{cleanName}}</b></div>
                            <div><span style="background:${{sideColor}}22; color:${{sideColor}}; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold;">${{pos.side}} (${{data.leverage}}x)</span></div>
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:10px;">
                            <div>Preço Atual: <b style="color:${{sideColor}};">${{pos.current_price.toFixed(5)}}</b></div>
                        </div>
                        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:5px; font-size:11px; text-align:center; color:#94a3b8; margin-bottom:8px;">
                            <div style="background:#0b0f19; padding:6px; border-radius:4px;">PNL (%)<br>${{formatColoredPct(pnlPct)}}</div>
                            <div style="background:#0b0f19; padding:6px; border-radius:4px;">PNL (USDT)<br>${{formatColoredValue(pnlUsdt, 4)}}</div>
                        </div>
                        <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:5px; font-size:11px; text-align:center; color:#94a3b8;">
                            <div style="background:#0b0f19; padding:4px; border-radius:4px;">ENTRADA<br><b style="color:#facc15;">${{pos.entry_price.toFixed(5)}}</b></div>
                            <div style="background:#0b0f19; padding:4px; border-radius:4px;">MÁXIMO<br><b style="color:#4ade80;">${{pos.highest_price.toFixed(5)}}</b></div>
                            <div style="background:#0b0f19; padding:4px; border-radius:4px;">MÍNIMO<br><b style="color:#f87171;">${{pos.lowest_price.toFixed(5)}}</b></div>
                        </div>
                    `;
                }} else {{
                    posCard.innerHTML = `<div style="color:#94a3b8; text-align:center; padding:15px;">Nenhuma posição ativa no momento.</div>`;
                }}

                const mercadoContainer = document.getElementById('mercado-container');
                let mercadoHtml = '';
                for (const [sym, info] of Object.entries(data.scanned_pairs)) {{
                    const tagColor = info.signal === 'SHORT' ? '#f87171' : (info.signal === 'LONG' ? '#4ade80' : '#94a3b8');
                    const cleanName = cleanCoinName(sym);
                    const signalText = info.signal || 'NEUTRO';
                    const signalBadge = `<span style="background:${{tagColor}}22; color:${{tagColor}}; padding:2px 6px; border-radius:4px; font-size:11px; font-weight:bold;">${{signalText}}</span>`;
                    
                    mercadoHtml += `
                        <div style="background:#161f31; padding:12px; border-radius:8px; margin-bottom:8px; border:1px solid #2a374a;">
                            <div style="margin-bottom:6px;">
                                <div style="font-size:20px; font-weight:900; color:#f8fafc; margin-bottom:2px;"><b>${{cleanName}}</b></div>
                                ${{signalBadge}}
                            </div>
                            <div style="font-size:12px; color:#94a3b8;">Preço: ${{info.price}} | RSI: ${{info.rsi.toFixed(1)}}</div>
                        </div>
                    `;
                }}
                mercadoContainer.innerHTML = mercadoHtml || '<p style="color:#94a3b8; text-align:center;">A carregar mercado...</p>';

                const histContainer = document.getElementById('historico-container');
                if (data.closed_trades.length === 0) {{
                    histContainer.innerHTML = '<p style="color:#94a3b8; text-align:center;">Nenhuma operação fechada ainda.</p>';
                }} else {{
                    let histHtml = '';
                    for (const t of data.closed_trades) {{
                        const cleanName = cleanCoinName(t.symbol);
                        histHtml += `
                            <div style="background:#161f31; padding:12px; border-radius:8px; margin-bottom:8px; border:1px solid #2a374a;">
                                <div style="margin-bottom:4px;">
                                    <div style="font-size:18px; font-weight:900; color:#f8fafc; margin-bottom:2px;"><b>${{cleanName}} (${{t.side}})</b></div>
                                    <div>${{formatColoredValue(t.pnl_usdt)}} USDT</div>
                                </div>
                                <small style="color:#94a3b8;">Fechado via ${{t.reason || 'Trailing Stop'}}</small>
                            </div>
                        `;
                    }}
                    histContainer.innerHTML = histHtml;
                }}
            }} catch (err) {{
                console.error("Erro no polling da UI:", err);
            }}
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

@app.post("/toggle_bot", response_class=HTMLResponse)
async def toggle_bot():
    global bot_running, active_position, total_realized_pnl, initial_account_balance, closed_trades, last_api_error
    bot_running = not bot_running
    
    if not bot_running and active_position:
        try:
            symbol = active_position['symbol']
            side = active_position['side']
            entry_price = active_position['entry_price']
            curr_price = active_position.get('current_price', entry_price)
            amount = active_position['amount']
            leverage = int(config.load_config().get("LEVERAGE", 17))
            
            if exchange_mgr and exchange_mgr.exchange:
                positions = await exchange_mgr.exchange.fetch_positions([symbol])
                real_amt = amount
                for p in positions:
                    if p.get('symbol') == symbol:
                        sz = float(p.get('contracts', 0.0) or p.get('size', 0.0))
                        if sz > 0:
                            real_amt = sz
                            break
                
                await exchange_mgr.execute_market_order(symbol, 'SELL' if side == 'LONG' else 'BUY', real_amt, leverage=leverage, params={'reduceOnly': True})
            
            pnl_pct = (curr_price - entry_price) / entry_price if side == 'LONG' else (entry_price - curr_price) / entry_price
            pnl_usdt = pnl_pct * amount * entry_price * (leverage / 10)
            total_realized_pnl += pnl_usdt
            initial_account_balance += pnl_usdt
            
            closed_trades.insert(0, {
                'symbol': symbol,
                'side': side,
                'pnl_usdt': pnl_usdt,
                'reason': 'Paragem Manual do Utilizador'
            })
            
            active_position = None
            max_profit_reached = 0.0
            last_api_error = "Robô parado manualmente. Posição fechada com sucesso!"
        except Exception as e:
            last_api_error = f"Erro ao fechar na paragem manual: {str(e)}"
            logging.error(last_api_error)

    return """<html><meta http-equiv="refresh" content="0;url=/"><body></body></html>"""

@app.post("/save", response_class=HTMLResponse)
async def save_settings(api_key: str = Form(...), api_secret: str = Form(...), leverage: int = Form(17), is_testnet: bool = Form(False)):
    global initial_account_balance, total_realized_pnl
    config.save_config(api_key, api_secret, is_testnet, leverage)
    init_exchange_manager()
    initial_account_balance = 0.0
    total_realized_pnl = 0.0
    await fetch_live_balance()
    return """
    <html>
    <meta http-equiv="refresh" content="1;url=/">
    <body style="background:#0b0f19; color:white; font-family:Arial; text-align:center; padding-top:50px;">
        <h2 style="color:#4ade80;">Definições guardadas e alavancagem atualizada!</h2>
    </body>
    </html>
    """

async def trading_loop():
    global active_position, max_profit_reached, scanned_pairs_data, closed_trades, initial_account_balance, current_account_balance, total_realized_pnl, last_api_error
    while True:
        try:
            if not exchange_mgr or not exchange_mgr.exchange:
                init_exchange_manager()
                await asyncio.sleep(3)
                continue

            current_conf = config.load_config()
            leverage = int(current_conf.get("LEVERAGE", 17))

            await fetch_live_balance()

            # 1. VARREDURA DO MERCADO PRIMEIRO PARA OBTER OS SINAIS ATUAIS DE TODOS OS PARES
            t_start = time.time()
            tasks = [exchange_mgr.fetch_market_data(pair) for pair in config.PAIRS]
            results = await asyncio.gather(*tasks)

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
                    'signal': sig
                }

                if sig in ['LONG', 'SHORT'] and not best_sym:
                    best_sig = sig
                    best_sym = symbol

            # 2. SINCRONIZAÇÃO DE POSIÇÕES DA CORRETORA
            try:
                positions = await exchange_mgr.exchange.fetch_positions(config.PAIRS)
                real_pos = None
                for p in positions:
                    if float(p.get('contracts', 0.0) or p.get('size', 0.0)) > 0:
                        real_pos = p
                        break
                
                if real_pos:
                    sym = real_pos.get('symbol')
                    side_raw = real_pos.get('side', '').upper()
                    entry_p = float(real_pos.get('entryPrice', 0.0))
                    contracts = float(real_pos.get('contracts', 0.0) or real_pos.get('size', 0.0))
                    
                    if not active_position or active_position['symbol'] != sym:
                        active_position = {
                            'symbol': sym,
                            'side': 'LONG' if 'LONG' in side_raw or side_raw == 'BUY' else 'SHORT',
                            'entry_price': entry_p,
                            'current_price': entry_p,
                            'highest_price': entry_p,
                            'lowest_price': entry_p,
                            'amount': contracts,
                            'pnl_unrealized': 0.0
                        }
                        max_profit_reached = 0.0
                else:
                    if active_position and not bot_running:
                        active_position = None
                        max_profit_reached = 0.0
            except Exception as e:
                logging.error(f"Erro posições: {e}")

            # 3. GESTÃO DA POSIÇÃO ATIVA (AVALIAÇÃO DE SAÍDA POR SINAL OU TRAILING STOP)
            if active_position:
                symbol = active_position['symbol']
                entry_price = active_position['entry_price']
                side = active_position['side']
                
                curr_price = scanned_pairs_data.get(symbol, {}).get('price')
                if not curr_price:
                    try:
                        ticker = await exchange_mgr.exchange.fetch_ticker(symbol)
                        curr_price = ticker['last']
                    except Exception:
                        curr_price = entry_price

                if curr_price:
                    if curr_price > active_position.get('highest_price', entry_price):
                        active_position['highest_price'] = curr_price
                    if curr_price < active_position.get('lowest_price', entry_price):
                        active_position['lowest_price'] = curr_price

                    pnl_pct = (curr_price - entry_price) / entry_price if side == 'LONG' else (entry_price - curr_price) / entry_price
                    active_position['current_price'] = curr_price
                    active_position['pnl_unrealized'] = pnl_pct * leverage * 100

                    if pnl_pct > max_profit_reached:
                        max_profit_reached = pnl_pct

                    # Obtém o sinal atual do par ativo
                    current_pair_signal = scanned_pairs_data.get(symbol, {}).get('signal') # 'LONG', 'SHORT' ou None (Neutro)

                    should_close, close_reason = trading_engine.evaluate_exit_condition(
                        pnl_pct, max_profit_reached, side, current_pair_signal
                    )

                    if should_close:
                        try:
                            clean_sym = clean_name_log(symbol)
                            close_amount = active_position['amount']
                            
                            try:
                                positions = await exchange_mgr.exchange.fetch_positions([symbol])
                                for p in positions:
                                    if p.get('symbol') == symbol:
                                        sz = float(p.get('contracts', 0.0) or p.get('size', 0.0))
                                        if sz > 0:
                                            close_amount = sz
                                            break
                            except Exception:
                                pass

                            await exchange_mgr.execute_market_order(symbol, 'SELL' if side == 'LONG' else 'BUY', close_amount, leverage=leverage, params={'reduceOnly': True})
                            
                            pnl_usdt = pnl_pct * close_amount * entry_price * (leverage / 10)
                            total_realized_pnl += pnl_usdt
                            initial_account_balance += pnl_usdt
                            
                            closed_trades.insert(0, {
                                'symbol': symbol,
                                'side': side,
                                'pnl_usdt': pnl_usdt,
                                'reason': close_reason
                            })
                            active_position = None
                            max_profit_reached = 0.0
                            last_api_error = f"Fechado em {clean_sym} ({close_reason})!"
                        except Exception as e:
                            last_api_error = f"Erro fecho automático: {str(e)}"
                            logging.error(last_api_error)

            # 4. ABERTURA DE NOVAS ORDENS (APENAS SE O ROBÔ ESTIVER LIGADO E SEM POSIÇÃO ATIVA)
            if best_sig and best_sym and bot_running and not active_position:
                curr_price = scanned_pairs_data[best_sym]['price']
                
                if 'DOGE' in best_sym:
                    amount = 1.0
                elif 'XRP' in best_sym:
                    amount = 0.1
                else:
                    amount = 1.0

                try:
                    order = await exchange_mgr.execute_market_order(best_sym, best_sig, amount, leverage=leverage)
                    if order:
                        clean_sym = clean_name_log(best_sym)
                        active_position = {
                            'symbol': best_sym, 'side': best_sig,
                            'entry_price': curr_price,
                            'current_price': curr_price,
                            'highest_price': curr_price,
                            'lowest_price': curr_price,
                            'amount': amount,
                            'pnl_unrealized': 0.0
                        }
                        max_profit_reached = 0.0
                        last_api_error = f"Ordem ABERTA em {clean_sym} ({best_sig})!"
                except Exception as e:
                    clean_sym = clean_name_log(best_sym)
                    last_api_error = f"ERRO BYBIT (Margem/Lote): {str(e)}"
                    logging.error(last_api_error)

        except Exception as e:
            last_api_error = f"Erro no loop: {str(e)}"
            logging.error(last_api_error)

        await asyncio.sleep(config.SCAN_INTERVAL)

def clean_name_log(symbol):
    if not symbol:
        return ""
    return str(symbol).split('/')[0].upper()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(trading_loop())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
