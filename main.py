import time
import threading
import logging
import datetime
import ccxt
from flask import Flask, render_template_string, request, redirect, url_for, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

app = Flask(__name__)

bot_state = {
    "running": False,
    "api_key": "",
    "api_secret": "",
    "api_password": "",
    "is_demo": True,
    "leverage": 21,
    "initial_balance": 0.0,
    "balance": 0.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "market_data": [],
    "history": [],
    "last_update": "Aguardando...",
    "log": "Sistema pronto. Insira as credenciais em Ajustes."
}

PAIRS = ['ADA/USDT:USDT', 'XRP/USDT:USDT', 'DOGE/USDT:USDT', 'TRX/USDT:USDT']

global_exchange = None

def get_exchange():
    global global_exchange
    key = str(bot_state.get("api_key") or "").strip()
    secret = str(bot_state.get("api_secret") or "").strip()
    password = str(bot_state.get("api_password") or "").strip()

    if key and secret and password:
        if global_exchange is None:
            try:
                config = {
                    'apiKey': key,
                    'secret': secret,
                    'password': password,
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'linear',
                        'adjustForTimeDifference': True
                    }
                }
                
                if bot_state.get("is_demo", True):
                    config['headers'] = {'x-simulated-trading': '1'}
                
                global_exchange = ccxt.okx(config)
                
                if bot_state.get("is_demo", True):
                    global_exchange.set_sandbox_mode(True)
                
                global_exchange.load_markets()
                bot_state["log"] = "Conexão OKX estabelecida com sucesso."
            except Exception as e:
                err_msg = str(e) if e else "Erro desconhecido"
                logging.error(f"Erro crítico CCXT OKX: {err_msg}")
                bot_state["log"] = str("Erro API: " + err_msg[:50])
                global_exchange = None
    return global_exchange

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OKX SCALPING</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 8px 8px 75px 8px; }
        .container { max-width: 480px; margin: auto; }
        h1 { color: #4ade80; text-align: center; font-size: 18px; margin: 8px 0 2px 0; font-weight: 700; }
        .clock { text-align: center; font-size: 11px; color: #38bdf8; margin-bottom: 10px; font-weight: bold; }
        
        .balance-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .balance-box { background: #1e293b; border: 1px solid #334155; padding: 10px; border-radius: 8px; text-align: center; }
        .balance-box span { display: block; font-size: 10px; color: #94a3b8; text-transform: uppercase; margin-bottom: 2px; }
        .balance-box strong { font-size: 14px; color: #4ade80; }
        
        .card { background: #1e293b; border: 1px solid #334155; padding: 12px; border-radius: 8px; margin-bottom: 10px; }
        .card h3 { color: #38bdf8; font-size: 12px; margin-top: 0; margin-bottom: 8px; text-transform: uppercase; }
        
        input[type="text"], input[type="password"], input[type="number"] { width: 100% !important; padding: 8px; margin-top: 4px; margin-bottom: 8px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #fff; box-sizing: border-box; font-size: 14px; }
        .checkbox-container { display: flex; align-items: center; gap: 8px; margin: 8px 0; font-size: 13px; color: #cbd5e1; cursor: pointer; }
        
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #1e293b; border-top: 1px solid #334155; display: flex; justify-content: space-around; align-items: center; padding: 6px 0; z-index: 100; height: 50px; }
        .nav-btn { background: none; border: none; color: #94a3b8; font-size: 10px; font-weight: bold; cursor: pointer; text-align: center; flex: 1; }
        .nav-btn.active { color: #4ade80; }
        
        .center-toggle-container { flex: 0; display: flex; justify-content: center; position: relative; bottom: 10px; }
        .btn-circle { width: 44px; height: 44px; border-radius: 50%; border: none; display: flex; align-items: center; justify-content: center; font-size: 18px; cursor: pointer; color: white; }
        .btn-circle.start { background: #16a34a; }
        .btn-circle.stop { background: #dc2626; }

        .log-box { background: #0f172a; border-left: 3px solid #f87171; padding: 8px; border-radius: 4px; font-size: 11px; color: #fca5a5; word-break: break-all; max-height: 90px; overflow-y: auto; }
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
            setInterval(function() {
                fetch('/api/state')
                    .then(response => response.json())
                    .then(data => {
                        if(data.log) {
                            let logBox = document.querySelector('.log-box');
                            if(logBox) logBox.innerText = data.log;
                        }
                        if(data.last_update) {
                            let clock = document.querySelector('.clock');
                            if(clock) clock.innerText = "Sincronizado: " + data.last_update;
                        }
                    }).catch(err => console.log(err));
            }, 2000);
        }
    </script>
</head>
<body>
    <div class="container">
        <h1>OKX SCALPING</h1>
        <div class="clock">Sincronizado: {{ last_update }}</div>

        <!-- ABA DASHBOARD -->
        <div id="dashboard" class="tab-content active">
            {% if configured %}
            <div class="balance-grid">
                <div class="balance-box">
                    <span>Inicial</span>
                    <strong>+{{ "%.2f"|format(initial_balance) }}</strong>
                </div>
                <div class="balance-box">
                    <span>Disponível ({{ 'DEMO' if is_demo else 'REAL' }})</span>
                    <strong>+{{ "%.2f"|format(balance) }}</strong>
                </div>
            </div>
            {% else %}
            <div class="card" style="border-left: 3px solid #f87171; text-align: center;">
                <p style="color: #f87171; margin: 0; font-weight: bold; font-size: 12px;">Credenciais OKX em falta!</p>
            </div>
            {% endif %}

            <div class="card">
                <h3>Posição Ativa</h3>
                {% if active_position %}
                    <p>Ativo: <b>{{ active_position.pair }}</b> ({{ active_position.side }})</p>
                    <p>Entrada: <b>{{ active_position.entry }}</b> | PNL: <b style="color: {{ '#4ade80' if active_position.pnl >= 0 else '#f87171' }}">{{ "+%.2f"|format(active_position.pnl) if active_position.pnl >= 0 else "%.2f"|format(active_position.pnl) }}%</b></p>
                {% else %}
                    <p style="text-align: center; color: #94a3b8; font-size: 12px;">Em Stand-by (Aguardando Sinal).</p>
                {% endif %}
            </div>

            <div class="card">
                <h3>Capital & Alavancagem</h3>
                <p>Alavancagem: <b>{{ leverage }}x</b> | Poder: <b>+{{ "%.2f"|format(balance * leverage) }}</b></p>
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
                    <span>Saldo OKX</span>
                    <strong>+{{ "%.2f"|format(balance) }}</strong>
                </div>
                <div class="balance-box">
                    <span>Ativos</span>
                    <strong style="color: #38bdf8;">{{ market_data|length }} Pares</strong>
                </div>
            </div>
            {% endif %}

            <div class="card">
                <h3>Mercado em Tempo Real</h3>
                {% for item in market_data %}
                <div class="market-item">
                    <div>
                        <b>{{ item.pair }}</b> <small style="color: #94a3b8;">(RSI: {{ "%.1f"|format(item.rsi_5m) }})</small><br>
                        <span style="font-size: 12px; color: #cbd5e1;">{{ item.price }}</span>
                    </div>
                    <span style="color: {{ '#4ade80' if item.trend == 'LONG' else ('#f87171' if item.trend == 'SHORT' else '#94a3b8') }}; font-weight: bold; font-size: 12px;">
                        {{ item.trend }}
                    </span>
                </div>
                {% else %}
                <p style="text-align: center; color: #94a3b8; font-size: 12px;">A carregar mercado...</p>
                {% endfor %}
            </div>
        </div>

        <!-- ABA HISTÓRICO -->
        <div id="historico" class="tab-content">
            <div class="card">
                <h3>Resumo Geral de Operações</h3>
                <p style="font-size: 12px;">Total Trades: <b>{{ history|length }}</b></p>
            </div>
        </div>

        <!-- ABA AJUSTES -->
        <div id="ajustes" class="tab-content">
            <div class="card">
                <h3>Configuração OKX API</h3>
                <form action="/settings" method="POST">
                    <label style="font-size: 11px; color: #94a3b8;">API Key:</label>
                    <input type="text" name="api_key" value="{{ api_key }}">
                    
                    <label style="font-size: 11px; color: #94a3b8;">API Secret:</label>
                    <input type="text" name="api_secret" value="{{ api_secret }}">
                    
                    <label style="font-size: 11px; color: #94a3b8;">API Password (Passphrase):</label>
                    <input type="text" name="api_password" value="{{ api_password }}">
                    
                    <label style="font-size: 11px; color: #94a3b8;">Alavancagem:</label>
                    <input type="number" name="leverage" value="{{ leverage }}" min="1" max="50" required>
                    
                    <label class="checkbox-container">
                        <input type="checkbox" name="is_demo" {% if is_demo %}checked{% endif %}>
                        Usar Modo Demo / Sandbox (Testes)
                    </label>
                    
                    <button type="submit" style="width: 100%; padding: 10px; border-radius: 6px; border: none; font-size: 14px; font-weight: bold; cursor: pointer; background: #16a34a; color: white; margin-top: 6px;">Guardar Definições</button>
                </form>
            </div>
        </div>

        <div class="nav-bar">
            <button id="btn-dashboard" class="nav-btn active" onclick="showTab('dashboard')">📊<br>Dashboard</button>
            <button id="btn-mercado" class="nav-btn" onclick="showTab('mercado')">📈<br>Mercado</button>
            
            <div class="center-toggle-container">
                <form action="/toggle" method="POST" style="margin:0;">
                    <button type="submit" class="btn-circle {{ 'stop' if running else 'start' }}">
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

def fetch_market_and_balance():
    key = str(bot_state.get("api_key") or "").strip()
    secret = str(bot_state.get("api_secret") or "").strip()
    password = str(bot_state.get("api_password") or "").strip()

    if not key or not secret or not password:
        return

    exchange = get_exchange()
    if not exchange:
        return

    try:
        balance_data = exchange.fetch_balance()
        total = 0.0
        if isinstance(balance_data, dict):
            total_dict = balance_data.get('total')
            if isinstance(total_dict, dict) and total_dict.get('USDT') is not None:
                total = float(total_dict['USDT'])

        if total > 0:
            if float(bot_state["initial_balance"]) == 0.0:
                bot_state["initial_balance"] = total
            bot_state["balance"] = total
    except Exception as e:
        err_str = str(e) if e else "Erro de leitura"
        logging.error(f"Erro a ler saldo OKX: {err_str}")
        bot_state["log"] = str("Erro Saldo: " + err_str[:40])

    market_list = []
    for symbol in PAIRS:
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = float(ticker.get('last') or 0.0)
            clean_name = symbol.split('/')[0]
            market_list.append({
                "pair": clean_name,
                "symbol": symbol,
                "price": current_price,
                "rsi_5m": 50.0,
                "trend": "NEUTRO"
            })
        except Exception as ex:
            logging.error(f"Erro no par {symbol}: {ex}")

    if market_list:
        bot_state["market_data"] = market_list
    
    bot_state["last_update"] = str(datetime.datetime.now().strftime("%H:%M:%S"))

@app.route('/api/state')
def api_state():
    return jsonify({
        "log": str(bot_state.get("log") or "Aguardando..."),
        "last_update": str(bot_state.get("last_update") or "Aguardando...")
    })

@app.route('/')
def index():
    key = str(bot_state.get("api_key") or "").strip()
    secret = str(bot_state.get("api_secret") or "").strip()
    password = str(bot_state.get("api_password") or "").strip()

    if key and secret and password:
        fetch_market_and_balance()

    configured = bool(key and secret and password)
    return render_template_string(
        HTML_TEMPLATE,
        configured=configured,
        running=bool(bot_state.get("running", False)),
        initial_balance=float(bot_state.get("initial_balance") or 0.0),
        balance=float(bot_state.get("balance") or 0.0),
        realized_pnl=float(bot_state.get("realized_pnl") or 0.0),
        active_position=bot_state.get("active_position"),
        market_data=bot_state.get("market_data", []),
        history=bot_state.get("history", []),
        api_key=str(bot_state.get("api_key") or ""),
        api_secret=str(bot_state.get("api_secret") or ""),
        api_password=str(bot_state.get("api_password") or ""),
        is_demo=bool(bot_state.get("is_demo", True)),
        leverage=int(bot_state.get("leverage") or 21),
        last_update=str(bot_state.get("last_update") or "Aguardando..."),
        log=str(bot_state.get("log") or "Sistema pronto.")
    )

@app.route('/settings', methods=['POST'])
def settings():
    global global_exchange
    global_exchange = None 
    
    bot_state["api_key"] = str(request.form.get("api_key") or "").strip()
    bot_state["api_secret"] = str(request.form.get("api_secret") or "").strip()
    bot_state["api_password"] = str(request.form.get("api_password") or "").strip()
    bot_state["is_demo"] = True if request.form.get("is_demo") else False
    
    try:
        bot_state["leverage"] = int(request.form.get("leverage") or 21)
    except ValueError:
        bot_state["leverage"] = 21
    
    fetch_market_and_balance()
    bot_state["log"] = str("Definições guardadas com sucesso.")
    return redirect(url_for('index'))

@app.route('/toggle', methods=['POST'])
def toggle():
    key = str(bot_state.get("api_key") or "").strip()
    secret = str(bot_state.get("api_secret") or "").strip()
    password = str(bot_state.get("api_password") or "").strip()

    if not key or not secret or not password:
        bot_state["log"] = str("Erro: Credenciais em falta nos Ajustes!")
        return redirect(url_for('index'))
    
    bot_state["running"] = not bot_state.get("running", False)
    mode_str = "DEMO" if bot_state.get("is_demo", True) else "REAL"
    status_txt = "Robô ativado (" + mode_str + ")." if bot_state["running"] else "Robô parado."
    bot_state["log"] = str(status_txt)
    return redirect(url_for('index'))

def background_loop():
    global global_exchange
    while True:
        try:
            key = str(bot_state.get("api_key") or "").strip()
            secret = str(bot_state.get("api_secret") or "").strip()
            password = str(bot_state.get("api_password") or "").strip()

            if key and secret and password:
                fetch_market_and_balance()
        except Exception as e:
            logging.error(f"Erro no loop principal: {e}")
            global_exchange = None
        
        time.sleep(2)

if __name__ == '__main__':
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
