import time
import threading
import logging
import ccxt
from flask import Flask, render_template_string, request, redirect, url_for

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

app = Flask(__name__)

bot_state = {
    "running": False,
    "api_key": "",
    "api_secret": "",
    "is_testnet": False,
    "leverage": 17,
    "initial_balance": 0.0,
    "balance": 0.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "market_data": [],
    "history": [],
    "log": "Sistema inicializado. Insira as chaves em Ajustes."
}

PAIRS = ['ADA/USDT', 'TRX/USDT', 'NEAR/USDT', 'LTC/USDT']

TAKE_PROFIT_PCT = 0.045     # 4.5%
STOP_LOSS_PCT = 0.012       # 1.2%
TRAILING_ACTIVATE_PCT = 0.005 # 0.5%

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ND-SCALPING PRO</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 8px 8px 75px 8px; }
        .container { max-width: 480px; margin: auto; }
        h1 { color: #4ade80; text-align: center; font-size: 18px; margin: 8px 0 12px 0; font-weight: 700; letter-spacing: 0.5px; }
        
        .balance-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .balance-box { background: #1e293b; border: 1px solid #334155; padding: 10px; border-radius: 8px; text-align: center; }
        .balance-box span { display: block; font-size: 10px; color: #94a3b8; text-transform: uppercase; margin-bottom: 2px; }
        .balance-box strong { font-size: 14px; color: #4ade80; }
        
        .card { background: #1e293b; border: 1px solid #334155; padding: 12px; border-radius: 8px; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .card h3 { color: #38bdf8; font-size: 12px; margin-top: 0; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.3px; }
        
        input[type="text"], input[type="password"], input[type="number"] { width: 100% !important; max-width: 100% !important; padding: 8px; margin-top: 4px; margin-bottom: 8px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #fff; box-sizing: border-box; font-size: 14px; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #1e293b; border-top: 1px solid #334155; display: flex; justify-content: space-around; align-items: center; padding: 6px 0; z-index: 100; height: 50px; }
        .nav-btn { background: none; border: none; color: #94a3b8; font-size: 10px; font-weight: bold; cursor: pointer; text-align: center; flex: 1; }
        .nav-btn.active { color: #4ade80; }
        
        .center-toggle-container { flex: 0; display: flex; justify-content: center; position: relative; bottom: 10px; }
        .btn-circle { width: 44px; height: 44px; border-radius: 50%; border: none; display: flex; align-items: center; justify-content: center; font-size: 18px; cursor: pointer; box-shadow: 0 3px 8px rgba(0,0,0,0.3); color: white; transition: transform 0.1s; }
        .btn-circle:active { transform: scale(0.95); }
        .btn-circle.start { background: #16a34a; }
        .btn-circle.stop { background: #dc2626; }

        .log-box { background: #0f172a; border-left: 3px solid #38bdf8; padding: 8px; border-radius: 4px; font-size: 11px; color: #cbd5e1; word-break: break-all; max-height: 80px; overflow-y: auto; }
        .market-item { display: flex; justify-content: space-between; align-items: center; background: #334155; padding: 8px 10px; border-radius: 6px; margin-bottom: 6px; font-size: 13px; }
        .history-item { background: #334155; padding: 8px 10px; border-radius: 6px; margin-bottom: 6px; font-size: 12px; display: flex; justify-content: space-between; align-items: center; }
        p { margin: 6px 0; font-size: 13px; }
    </style>
    <script>
        function showTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            if(document.getElementById('btn-' + tabId)) {
                document.getElementById('btn-' + tabId).classList.add('active');
            }
            localStorage.setItem('activeTab', tabId);
        }

        window.onload = function() {
            let savedTab = localStorage.getItem('activeTab');
            if (savedTab && document.getElementById(savedTab)) {
                showTab(savedTab);
            }
        }
    </script>
</head>
<body>
    <div class="container">
        <h1>ND-SCALPING</h1>

        <!-- ABA DASHBOARD -->
        <div id="dashboard" class="tab-content active">
            {% if configured %}
            <div class="balance-grid">
                <div class="balance-box">
                    <span>Inicial</span>
                    <strong>+{{ "%.6f"|format(initial_balance) }}</strong>
                </div>
                <div class="balance-box">
                    <span>Atual</span>
                    <strong>+{{ "%.6f"|format(balance) }}</strong>
                </div>
            </div>
            {% else %}
            <div class="card" style="border-left: 3px solid #f87171; text-align: center;">
                <p style="color: #f87171; margin: 0; font-weight: bold; font-size: 12px;">Chaves API em falta!</p>
                <small style="color: #94a3b8; font-size: 11px;">Configure na aba Ajustes.</small>
            </div>
            {% endif %}

            <div class="card">
                <h3>Posição Ativa</h3>
                {% if active_position %}
                    <p>Ativo: <b>{{ active_position.pair }}</b> ({{ active_position.side }})</p>
                    <p>Entrada: <b>{{ active_position.entry }}</b> | PNL: <b style="color: {{ '#4ade80' if active_position.pnl >= 0 else '#f87171' }}">{{ "+%.2f"|format(active_position.pnl) if active_position.pnl >= 0 else "%.2f"|format(active_position.pnl) }}%</b></p>
                    <small style="color: #38bdf8;">Muralha Trailing: {{ 'ATIVADA (Rigorosa)' if active_position.trailing_active else 'Inativa (<0.5%)' }}</small>
                {% else %}
                    <p style="text-align: center; color: #94a3b8; font-size: 12px;">Nenhuma posição ativa.</p>
                {% endif %}
            </div>

            <div class="card">
                <h3>Capital & Alavancagem</h3>
                <p>Alavancagem: <b>{{ leverage }}x</b> | Poder: <b>+{{ "%.4f"|format(balance * leverage) }}</b></p>
            </div>

            <div class="balance-grid">
                <div class="balance-box">
                    <span>Status</span>
                    <strong style="color: {{ '#4ade80' if running else '#f87171' }}; font-size: 13px;">{{ 'OPERANDO' if running else 'PARADO' }}</strong>
                </div>
                <div class="balance-box">
                    <span>PNL Realizado</span>
                    <strong style="font-size: 13px;">{{ "%.4f"|format(realized_pnl) }}</strong>
                </div>
            </div>

            <div class="card">
                <h3>Log do Sistema</h3>
                <div class="log-box">{{ log }}</div>
            </div>
        </div>

        <!-- ABA MERCADO -->
        <div id="mercado" class="tab-content">
            {% if configured %}
            <div class="balance-grid" style="margin-bottom: 10px;">
                <div class="balance-box">
                    <span>Saldo Disponível</span>
                    <strong>+{{ "%.4f"|format(balance) }}</strong>
                </div>
                <div class="balance-box">
                    <span>Ativos</span>
                    <strong style="color: #38bdf8;">{{ market_data|length }} Pares</strong>
                </div>
            </div>
            {% endif %}

            <div class="card">
                <h3>Mercado em Tempo Real (5m / 15m)</h3>
                {% for item in market_data %}
                <div class="market-item">
                    <div>
                        <b>{{ item.pair }}</b> <small style="color: #94a3b8;">(RSI 5m: {{ "%.1f"|format(item.rsi_5m) }} | 15m: {{ "%.1f"|format(item.rsi_15m) }})</small><br>
                        <span style="font-size: 12px; color: #cbd5e1;">{{ item.price }}</span>
                    </div>
                    <span style="color: {{ '#4ade80' if item.trend == 'LONG' else ('#f87171' if item.trend == 'SHORT' else '#94a3b8') }}; font-weight: bold; font-size: 12px;">
                        {{ item.trend }}
                    </span>
                </div>
                {% else %}
                <p style="text-align: center; color: #94a3b8; font-size: 12px;">{{ 'Insira as chaves em Ajustes.' if not configured else 'A sincronizar com a Bybit...' }}</p>
                {% endfor %}
            </div>
        </div>

        <!-- ABA HISTÓRICO -->
        <div id="historico" class="tab-content">
            <div class="card">
                <h3>Resumo Geral</h3>
                {% set total_trades = history|length %}
                {% set pos_count = namespace(val=0) %}
                {% set neg_count = namespace(val=0) %}
                {% set total_usdt = namespace(val=0.0) %}
                {% set total_pct = namespace(val=0.0) %}
                
                {% for h in history %}
                    {% set total_usdt.val = total_usdt.val + h.pnl_usdt %}
                    {% set total_pct.val = total_pct.val + h.pnl_pct %}
                    {% if h.pnl_usdt >= 0 %}
                        {% set pos_count.val = pos_count.val + 1 %}
                    {% else %}
                        {% set neg_count.val = neg_count.val + 1 %}
                    {% endif %}
                {% endfor %}

                <p style="font-size: 12px;">Total: <b>{{ total_trades }}</b> | Pos: <b style="color: #4ade80;">{{ pos_count.val }}</b> | Neg: <b style="color: #f87171;">{{ neg_count.val }}</b></p>
                <p style="font-size: 12px;">Resultado: <b style="color: {{ '#4ade80' if total_usdt.val >= 0 else '#f87171' }}">{{ "+%.4f"|format(total_usdt.val) if total_usdt.val >= 0 else "%.4f"|format(total_usdt.val) }} USDT</b> ({{ "+%.2f"|format(total_pct.val) if total_pct.val >= 0 else "%.2f"|format(total_pct.val) }}%)</p>
            </div>

            <div class="card">
                <h3>Registo de Operações</h3>
                {% for h in history %}
                <div class="history-item">
                    <div>
                        <b>{{ h.pair }} ({{ h.side }})</b><br>
                        <small style="color: #94a3b8; font-size: 10px;">{{ h.reason }}</small>
                    </div>
                    <div style="text-align: right;">
                        <span style="color: {{ '#4ade80' if h.pnl_usdt >= 0 else '#f87171' }}; font-weight: bold; font-size: 12px;">
                            {{ "+%.4f"|format(h.pnl_usdt) if h.pnl_usdt >= 0 else "%.4f"|format(h.pnl_usdt) }}
                        </span><br>
                        <small style="color: {{ '#4ade80' if h.pnl_pct >= 0 else '#f87171' }}; font-size: 10px;">
                            {{ "+%.2f"|format(h.pnl_pct) if h.pnl_pct >= 0 else "%.2f"|format(h.pnl_pct) }}%
                        </small>
                    </div>
                </div>
                {% else %}
                <p style="text-align: center; color: #94a3b8; font-size: 12px;">Nenhum registo recente.</p>
                {% endfor %}
            </div>
        </div>

        <!-- ABA AJUSTES -->
        <div id="ajustes" class="tab-content">
            <div class="card">
                <h3>Configuração API</h3>
                <form action="/settings" method="POST">
                    <label style="font-size: 11px; color: #94a3b8;">API Key:</label>
                    <input type="text" name="api_key" value="{{ api_key }}" required>
                    
                    <label style="font-size: 11px; color: #94a3b8;">API Secret:</label>
                    <input type="password" name="api_secret" value="{{ api_secret }}" required>
                    
                    <label style="font-size: 11px; color: #94a3b8;">Alavancagem:</label>
                    <input type="number" name="leverage" value="{{ leverage }}" min="1" max="50" required>
                    
                    <button type="submit" style="width: 100%; padding: 10px; border-radius: 6px; border: none; font-size: 14px; font-weight: bold; cursor: pointer; background: #16a34a; color: white; margin-top: 6px;">Guardar Definições</button>
                </form>
            </div>
        </div>

        <!-- BARRA DE NAVEGAÇÃO INFERIOR -->
        <div class="nav-bar">
            <button id="btn-dashboard" class="nav-btn active" onclick="showTab('dashboard')">📊<br>Dashboard</button>
            <button id="btn-mercado" class="nav-btn" onclick="showTab('mercado')">📈<br>Mercado</button>
            
            <div class="center-toggle-container">
                <form action="/toggle" method="POST" style="margin:0;">
                    <button type="submit" class="btn-circle {{ 'stop' if running else 'start' }}" title="{{ 'Parar Robô' if running else 'Iniciar Robô' }}">
                        {{ '⏹' if running else '▶' }}
                    </button>
                </form>
            </div>

            <button id="btn-historico" class="nav-btn" onclick="showTab('historico')">📋<br>Histórico</button>
            <button id="btn-ajustes" class="nav-btn" onclick="showTab('ajustes')">⚙️<br>Ajustes</button>
        </div>
    </div>
</body>
</html>
"""

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i-1]
        if diff > 0: gains += diff
        else: losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * 13 + gain) / 14
        avg_loss = (avg_loss * 13 + loss) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

@app.route('/')
def index():
    configured = bool(bot_state["api_key"] and bot_state["api_secret"])
    return render_template_string(
        HTML_TEMPLATE,
        configured=configured,
        running=bot_state["running"],
        initial_balance=bot_state["initial_balance"],
        balance=bot_state["balance"],
        realized_pnl=bot_state["realized_pnl"],
        active_position=bot_state["active_position"],
        market_data=bot_state["market_data"],
        history=bot_state["history"],
        api_key=bot_state["api_key"],
        api_secret="" if not bot_state["api_secret"] else "********",
        leverage=bot_state["leverage"],
        log=bot_state["log"]
    )

@app.route('/settings', methods=['POST'])
def settings():
    key = request.form.get("api_key", "").strip()
    secret = request.form.get("api_secret", "").strip()
    
    if key and key != "********":
        bot_state["api_key"] = key
    if secret and not secret.startswith("****") and secret != "********":
        bot_state["api_secret"] = secret
        
    try:
        bot_state["leverage"] = int(request.form.get("leverage", 17))
    except ValueError:
        pass
    
    bot_state["log"] = "Definições guardadas. Sincronizando Bybit..."
    return redirect(url_for('index'))

@app.route('/toggle', methods=['POST'])
def toggle():
    if not bot_state["api_key"] or not bot_state["api_secret"]:
        bot_state["log"] = "Erro: Insira as chaves API nos Ajustes primeiro!"
        return redirect(url_for('index'))
    
    bot_state["running"] = not bot_state["running"]
    bot_state["log"] = "Robô ativado e operando com muralha rigorosa." if bot_state["running"] else "Robô parado."
    return redirect(url_for('index'))

def background_loop():
    while True:
        try:
            if bot_state["api_key"] and bot_state["api_secret"]:
                exchange = ccxt.bybit({
                    'apiKey': bot_state["api_key"],
                    'secret': bot_state["api_secret"],
                    'enableRateLimit': True,
                    'options': {'defaultType': 'linear'}
                })
                
                exchange.load_markets()
                
                # Leitura robusta do saldo UTA V5
                bal = exchange.fetch_balance({'type': 'unified'})
                total = 0.0
                if 'total' in bal and 'USDT' in bal['total'] and bal['total']['USDT'] is not None:
                    total = float(bal['total']['USDT'])
                elif 'info' in bal and isinstance(bal['info'], dict):
                    res_list = bal['info'].get('result', {}).get('list', [])
                    if res_list:
                        for coin in res_list[0].get('coin', []):
                            if coin.get('coin') == 'USDT':
                                total = float(coin.get('walletBalance', 0.0) or coin.get('equity', 0.0))
                                break
                
                if total == 0.0 and 'free' in bal and 'USDT' in bal['free']:
                    total = float(bal['free'].get('USDT', 0.0)) + float(bal.get('used', {}).get('USDT', 0.0))

                if total > 0:
                    if bot_state["initial_balance"] == 0.0:
                        bot_state["initial_balance"] = total
                    bot_state["balance"] = total

                # Leitura de Mercado Multitimeframe (5m e 15m)
                market_list = []
                for base_pair in PAIRS:
                    symbol = base_pair
                    if symbol not in exchange.markets:
                        if f"{base_pair}:USDT" in exchange.markets:
                            symbol = f"{base_pair}:USDT"
                        elif f"{base_pair}/USDT:USDT" in exchange.markets:
                            symbol = f"{base_pair}/USDT:USDT"

                    try:
                        ticker = exchange.fetch_ticker(symbol)
                        current_price = ticker.get('last', 0.0)
                        
                        ohlcv_5m = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=50)
                        closes_5m = [c[4] for c in ohlcv_5m]
                        rsi_5m = calculate_rsi(closes_5m)
                        
                        ohlcv_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
                        closes_15m = [c[4] for c in ohlcv_15m]
                        rsi_15m = calculate_rsi(closes_15m)

                        if rsi_5m < 35 and rsi_15m < 45:
                            trend = "LONG"
                        elif rsi_5m > 65 and rsi_15m > 55:
                            trend = "SHORT"
                        else:
                            trend = "NEUTRO"

                        market_list.append({
                            "pair": base_pair.split('/')[0],
                            "symbol": symbol,
                            "price": current_price,
                            "rsi_5m": rsi_5m,
                            "rsi_15m": rsi_15m,
                            "trend": trend
                        })
                    except Exception as ex:
                        logging.error(f"Erro ao ler par {symbol}: {ex}")

                if market_list:
                    bot_state["market_data"] = market_list

                # Gestão de Posição Ativa e Muralha Trailing Stop
                if bot_state["running"]:
                    pos = bot_state["active_position"]
                    if pos:
                        symbol = pos["symbol"]
                        ticker = exchange.fetch_ticker(symbol)
                        current_price = ticker.get('last', 0.0)
                        entry_price = pos["entry"]
                        side = pos["side"]

                        if side == "LONG":
                            pnl_pct = (current_price - entry_price) / entry_price
                        else:
                            pnl_pct = (entry_price - current_price) / entry_price
                        
                        pos["pnl"] = pnl_pct * 100.0

                        if pnl_pct >= TRAILING_ACTIVATE_PCT:
                            if not pos["trailing_active"]:
                                pos["trailing_active"] = True
                                pos["highest_price"] = current_price
                                bot_state["log"] = f"Muralha ativada em {pos['pair']} (+{pnl_pct*100:.2f}%)!"

                        if pos["trailing_active"]:
                            if side == "LONG" and current_price > pos["highest_price"]:
                                pos["highest_price"] = current_price
                            elif side == "SHORT" and current_price < pos["highest_price"]:
                                pos["highest_price"] = current_price

                            if side == "LONG" and current_price < pos["highest_price"]:
                                bot_state["log"] = f"Muralha rigorosa acionada! Fechando {pos['pair']} por recuo."
                                bot_state["history"].append({
                                    "pair": pos["pair"], "side": side,
                                    "pnl_usdt": (pos["pnl"]/100) * bot_state["balance"],
                                    "pnl_pct": pos["pnl"], "reason": "Trailing Stop Rigoroso"
                                })
                                bot_state["realized_pnl"] += (pos["pnl"]/100) * bot_state["balance"]
                                bot_state["active_position"] = None
                            elif side == "SHORT" and current_price > pos["highest_price"]:
                                bot_state["log"] = f"Muralha rigorosa acionada! Fechando {pos['pair']} por recuo."
                                bot_state["history"].append({
                                    "pair": pos["pair"], "side": side,
                                    "pnl_usdt": (pos["pnl"]/100) * bot_state["balance"],
                                    "pnl_pct": pos["pnl"], "reason": "Trailing Stop Rigoroso"
                                })
                                bot_state["realized_pnl"] += (pos["pnl"]/100) * bot_state["balance"]
                                bot_state["active_position"] = None

                        elif pnl_pct >= TAKE_PROFIT_PCT:
                            bot_state["log"] = f"Take Profit (+4.5%) atingido em {pos['pair']}!"
                            bot_state["history"].append({
                                "pair": pos["pair"], "side": side,
                                "pnl_usdt": (pos["pnl"]/100) * bot_state["balance"],
                                "pnl_pct": pos["pnl"], "reason": "Take Profit Target"
                            })
                            bot_state["realized_pnl"] += (pos["pnl"]/100) * bot_state["balance"]
                            bot_state["active_position"] = None

                        elif pnl_pct <= -STOP_LOSS_PCT:
                            bot_state["log"] = f"Stop Loss (-1.2%) acionado em {pos['pair']}."
                            bot_state["history"].append({
                                "pair": pos["pair"], "side": side,
                                "pnl_usdt": (pos["pnl"]/100) * bot_state["balance"],
                                "pnl_pct": pos["pnl"], "reason": "Stop Loss Limit"
                            })
                            bot_state["realized_pnl"] += (pos["pnl"]/100) * bot_state["balance"]
                            bot_state["active_position"] = None
                    else:
                        for item in market_list:
                            if item["trend"] in ["LONG", "SHORT"]:
                                bot_state["active_position"] = {
                                    "pair": item["pair"],
                                    "symbol": item["symbol"],
                                    "side": item["trend"],
                                    "entry": item["price"],
                                    "highest_price": item["price"],
                                    "pnl": 0.0,
                                    "trailing_active": False
                                }
                                bot_state["log"] = f"Posição aberta: {item['pair']} ({item['trend']}) em {item['price']}"
                                break

        except Exception as e:
            err_msg = str(e)
            logging.error(f"Erro crítico no background_loop: {err_msg}")
            bot_state["log"] = f"Erro de conexão: {err_msg[:50]}"
        
        time.sleep(5)

if __name__ == '__main__':
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
