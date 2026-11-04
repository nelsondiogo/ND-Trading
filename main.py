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
    logging.error(f"Erro ao inicializar gestor da exchange: {e}")

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

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    global current_account_balance, initial_account_balance
    current_conf = config.load_config()
    current_leverage = current_conf.get("LEVERAGE", 10)
    
    if exchange_mgr and exchange_mgr.exchange:
        balance_data = {}
        try:
            # Tenta ler da conta de derivados/linear da Bybit
            balance_data = await exchange_mgr.exchange.fetch_balance({'accountType': 'UNIFIED'})
        except Exception:
            try:
                balance_data = await exchange_mgr.exchange.fetch_balance()
            except Exception as e:
                logging.error(f"Erro ao ler saldo: {e}")

        if balance_data:
            usdt_info = balance_data.get('USDT', {})
            live_bal = float(usdt_info.get('free', 0.0) or usdt_info.get('total', 0.0) or balance_data.get('free', {}).get('USDT', 0.0) or 0.0)
            
            if live_bal == 0.0 and 'info' in balance_data:
                try:
                    list_coins = balance_data['info'].get('result', {}).get('list', [])
                    for account in list_coins:
                        for coin in account.get('coin', []):
                            if coin.get('coin') == 'USDT':
                                live_bal = float(coin.get('walletBalance', 0.0) or coin.get('free', 0.0) or 0.0)
                except Exception:
                    pass

            if not bot_running:
                initial_account_balance = live_bal
                current_account_balance = live_bal
            else:
                current_account_balance = initial_account_balance + total_realized_pnl

    status_str = "OPERANDO" if bot_running else "PARADO"
    status_color = "#4ade80" if bot_running else "#f87171"
    multiplied_balance = current_account_balance * current_leverage

    active_card_html = "<div style='color:#94a3b8; text-align:center; padding:15px;'>Nenhuma posição ativa no momento.</div>"
    if active_position:
        side_color = "#f87171" if active_position['side'] == 'SHORT' else "#4ade80"
        active_card_html = f"""
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <b style="font-size:16px;">{active_position['symbol']}</b>
            <span style="background:{side_color}22; color:{side_color}; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold;">{active_position['side']} ({current_leverage}x)</span>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; font-size:13px; margin-bottom:12px;">
            <div><span style="color:#94a3b8; font-size:11px;">PNL N.REALIZ.</span><br><b style="color:{side_color};">{active_position.get('pnl_unrealized', 0.0):+.6f}</b></div>
            <div><span style="color:#94a3b8; font-size:11px;">PRECO</span><br><b>+{active_position.get('current_price', 0.0):.6f}</b></div>
            <div><span style="color:#94a3b8; font-size:11px;">ENTRADA</span><br><b style="color:#facc15;">+{active_position['entry_price']:.6f}</b></div>
            <div><span style="color:#94a3b8; font-size:11px;">SCORE OPORTUNIDADE</span><br><b>{active_position.get('score', 90)}%</b></div>
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
                <small style="color:#94a3b8;">ROTAÇÃO/TRAVA | Lucro Garantido</small>
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
                <b style="color:{tag_color};">{data['score']}% Prob.</b>
            </div>
            <div style="font-size:15px; font-weight:bold; margin-bottom:6px;">{sym}</div>
            <div style="font-size:12px; color:#94a3b8;">Preço: {data['price']} | RSI:{data['rsi']:.1f} (HFT Ativo)</div>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
            input[type="text"], input[type="password"], input[type="number"] {{ width: 100%; padding: 10px; margin-top: 5px; background: #0b0f19; border: 1px solid #2a374a; color: white; border-radius: 6px; box-sizing: border-box; }}
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

                <div class="card" style="border-left: 4px solid #38bdf8;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <span style="color:#94a3b8; font-size:12px;">ALAVANCAGEM MANUAL</span>
                        <span style="background:#38bdf822; color:#38bdf8; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold;">{current_leverage}x</span>
                    </div>
                    <div style="font-size:13px; color:#f8fafc;">
                        Saldo Real: <b style="color:#4ade80;">+{current_account_balance:.6f} USDT</b><br>
                        Poder de Compra ({current_leverage}x): <b style="color:#38bdf8;">+{multiplied_balance:.6f} USDT</b>
                    </div>
                </div>

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

                <form action="/toggle_bot" method="post">
                    <button type="submit" style="background:{('#ef4444' if bot_running else '#22c55e')};">{('PARAR ROBÔ' if bot_running else 'INICIAR ROBÔ')}</button>
                </form>
            </div>

            <div id="tab-mercado" class="tab-content">
                <div style="font-size:12px; color:#94a3b8; margin-bottom:10px;">MERCADO DINÂMICO (10 PARES HFT)</div>
                {mercado_html if mercado_html else "<p style='color:#94a3b8; text-align:center;'>A varrer mercado em tempo real...</p>"}
            </div>

            <div id="tab-grafico" class="tab-content">
                <div class="card" style="padding: 10px;">
                    <div style="font-size:12px; color:#38bdf8; font-weight:bold; margin-bottom:8px;">DOGEUSDT Perpetual Contract</div>
                    <iframe src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_widget&symbol=BYBIT%3ADOGEUSDT&interval=1&hidesidetoolbar=1&symboledit=1&saveimage=0&toolbarbg=1e293b&theme=dark&style=1&timezone=Etc%2FUTC" style="width:100%; height:320px; border:none; border-radius:8px;"></iframe>
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
                    <h2 style="color:#38bdf8; font-size:16px; margin-top:0;">Configuração & Alavancagem</h2>
                    <form action="/save" method="post">
                        <label style="font-size:12px; color:#94a3b8;">Bybit API Key:</label>
                        <input type="text" name="api_key" value="{current_conf['BYBIT_API_KEY']}" required>
                        
                        <label style="font-size:12px; color:#94a3b8; margin-top:10px; display:block;">Bybit API Secret:</label>
                        <input type="password" name="api_secret" value="{current_conf['BYBIT_API_SECRET']}" required>

                        <label style="font-size:12px; color:#94a3b8; margin-top:10px; display:block;">Alavancagem Manual (ex: 10, 20, 50):</label>
                        <input type="number" name="leverage" value="{current_leverage}" min="1" max="100" required>

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
