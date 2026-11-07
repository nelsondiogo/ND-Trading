import time
import threading
import datetime
import ccxt
from flask import Flask, render_template_string, request, redirect, url_for, jsonify

app = Flask(__name__)

bot_state = {
    "running": False,
    "api_key": "",
    "api_secret": "",
    "api_password": "",
    "is_demo": True,
    "leverage": 21,
    "balance": 0.0,
    "market_data": [],
    "log": "Sistema pronto. Insira as credenciais em Ajustes."
}

PAIRS = ['ADA/USDT:USDT', 'XRP/USDT:USDT', 'DOGE/USDT:USDT', 'TRX/USDT:USDT']
global_exchange = None

def get_exchange():
    global global_exchange
    if bot_state["api_key"] and bot_state["api_secret"] and bot_state["api_password"]:
        if global_exchange is None:
            try:
                config = {
                    'apiKey': bot_state["api_key"],
                    'secret': bot_state["api_secret"],
                    'password': bot_state["api_password"],
                    'enableRateLimit': True,
                    'options': {'defaultType': 'linear'}
                }
                if bot_state["is_demo"]:
                    config['headers'] = {'x-simulated-trading': '1'}
                
                global_exchange = ccxt.okx(config)
                if bot_state["is_demo"]:
                    global_exchange.set_sandbox_mode(True)
                global_exchange.load_markets()
                bot_state["log"] = "Conexão OKX estabelecida com sucesso."
            except Exception as e:
                bot_state["log"] = "Erro API: " + str(e)[:40]
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
        body { font-family: sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 8px 8px 70px 8px; }
        .container { max-width: 480px; margin: auto; }
        h1 { color: #4ade80; text-align: center; font-size: 18px; }
        .card { background: #1e293b; border: 1px solid #334155; padding: 12px; border-radius: 8px; margin-bottom: 10px; }
        input[type="text"], input[type="password"], input[type="number"] { width: 100%; padding: 8px; margin-top: 4px; margin-bottom: 8px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #fff; box-sizing: border-box; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #1e293b; border-top: 1px solid #334155; display: flex; justify-content: space-around; align-items: center; padding: 6px 0; height: 50px; }
        .nav-btn { background: none; border: none; color: #94a3b8; font-size: 11px; font-weight: bold; cursor: pointer; flex: 1; text-align: center; }
        .nav-btn.active { color: #4ade80; }
        .log-box { background: #0f172a; border-left: 3px solid #f87171; padding: 8px; font-size: 11px; color: #fca5a5; max-height: 80px; overflow-y: auto; }
        .btn-circle { width: 42px; height: 42px; border-radius: 50%; border: none; color: white; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; background: #16a34a; }
        .btn-circle.stop { background: #dc2626; }
    </style>
    <script>
        function showTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            document.getElementById('btn-' + tabId).classList.add('active');
        }
        setInterval(function() {
            fetch('/api/state').then(res => res.json()).then(data => {
                if(data.log) document.querySelector('.log-box').innerText = data.log;
            }).catch(e => {});
        }, 2000);
    </script>
</head>
<body>
    <div class="container">
        <h1>OKX SCALPING</h1>

        <div id="dashboard" class="tab-content active">
            <div class="card">
                <h3>Saldo Disponível</h3>
                <p style="font-size: 18px; color: #4ade80; font-weight: bold;">+{{ "%.2f"|format(balance) }} USDT</p>
            </div>
            <div class="card">
                <h3>Status do Robô</h3>
                <p>Estado: <b style="color: {{ '#4ade80' if running else '#f87171' }}">{{ 'OPERANDO' if running else 'PARADO' }}</b></p>
            </div>
            <div class="card">
                <h3>Log do Sistema</h3>
                <div class="log-box">{{ log }}</div>
            </div>
        </div>

        <div id="mercado" class="tab-content">
            <div class="card">
                <h3>Pares Monitorizados</h3>
                {% for item in market_data %}
                <p><b>{{ item.pair }}</b>: {{ item.price }}</p>
                {% else %}
                <p>Sem dados de mercado.</p>
                {% endfor %}
            </div>
        </div>

        <div id="ajustes" class="tab-content">
            <div class="card">
                <h3>Configuração API</h3>
                <form action="/settings" method="POST">
                    <label>API Key:</label>
                    <input type="text" name="api_key" value="{{ api_key }}">
                    <label>API Secret:</label>
                    <input type="text" name="api_secret" value="{{ api_secret }}">
                    <label>API Password (Passphrase):</label>
                    <input type="text" name="api_password" value="{{ api_password }}">
                    <label>Alavancagem:</label>
                    <input type="number" name="leverage" value="{{ leverage }}">
                    <button type="submit" style="width:100%; padding:10px; background:#16a34a; color:#fff; border:none; border-radius:6px; font-weight:bold; margin-top:10px;">Guardar</button>
                </form>
            </div>
        </div>

        <div class="nav-bar">
            <button id="btn-dashboard" class="nav-btn active" onclick="showTab('dashboard')">Dashboard</button>
            <button id="btn-mercado" class="nav-btn" onclick="showTab('mercado')">Mercado</button>
            <form action="/toggle" method="POST" style="margin:0; display:flex; align-items:center;">
                <button type="submit" class="btn-circle {{ 'stop' if running else '' }}">{{ '⏹' if running else '▶' }}</button>
            </form>
            <button id="btn-ajustes" class="nav-btn" onclick="showTab('ajustes')">Ajustes</button>
        </div>
    </div>
</body>
</html>
"""

def fetch_data():
    if not bot_state["api_key"] or not bot_state["api_secret"] or not bot_state["api_password"]:
        return
    ex = get_exchange()
    if not ex:
        return
    try:
        bal = ex.fetch_balance()
        total = float(bal.get('total', {}).get('USDT', 0.0) or 0.0)
        bot_state["balance"] = total

        m_list = []
        for sym in PAIRS:
            ticker = ex.fetch_ticker(sym)
            m_list.append({"pair": sym.split('/')[0], "price": ticker.get('last', 0.0)})
        bot_state["market_data"] = m_list
    except Exception as e:
        bot_state["log"] = "Erro loop: " + str(e)[:40]

@app.route('/api/state')
def api_state():
    return jsonify({"log": bot_state["log"]})

@app.route('/')
def index():
    if bot_state["api_key"]:
        fetch_data()
    return render_template_string(
        HTML_TEMPLATE,
        running=bot_state["running"],
        balance=bot_state["balance"],
        market_data=bot_state["market_data"],
        api_key=bot_state["api_key"],
        api_secret=bot_state["api_secret"],
        api_password=bot_state["api_password"],
        leverage=bot_state["leverage"],
        is_demo=bot_state["is_demo"],
        log=bot_state["log"]
    )

@app.route('/settings', methods=['POST'])
def settings():
    global global_exchange
    global_exchange = None
    bot_state["api_key"] = request.form.get("api_key", "").strip()
    bot_state["api_secret"] = request.form.get("api_secret", "").strip()
    bot_state["api_password"] = request.form.get("api_password", "").strip()
    try:
        bot_state["leverage"] = int(request.form.get("leverage", 21))
    except:
        bot_state["leverage"] = 21
    bot_state["log"] = "Definições guardadas."
    return redirect(url_for('index'))

@app.route('/toggle', methods=['POST'])
def toggle():
    if not bot_state["api_key"]:
        bot_state["log"] = "Insira as chaves primeiro!"
        return redirect(url_for('index'))
    bot_state["running"] = not bot_state["running"]
    bot_state["log"] = "Robô a funcionar." if bot_state["running"] else "Robô parado."
    return redirect(url_for('index'))

def background_loop():
    global global_exchange
    while True:
        try:
            if bot_state["running"]:
                fetch_data()
        except Exception as e:
            global_exchange = None
        time.sleep(3)

if __name__ == '__main__':
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
