import asyncio
import threading
import datetime
import ccxt.pro as ccxtpro
from flask import Flask, render_template_string, request, redirect, url_for, jsonify
from strategy import ScalpingEngine

app = Flask(__name__)

bot_state = {
    "running": False,
    "api_key": "",
    "api_secret": "",
    "is_demo": True,
    "leverage": 21,
    "initial_balance": 0.0,
    "balance": 0.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "market_data": [],
    "last_update": "Aguardando...",
    "log": "Motor HFT pronto. Configure as chaves Bybit."
}

PAIRS = ['ADA/USDT:USDT', 'XRP/USDT:USDT', 'DOGE/USDT:USDT', 'TRX/USDT:USDT']
global_exchange = None

async def async_main_loop():
    global global_exchange
    while True:
        if bot_state["running"]:
            key = bot_state["api_key"].strip()
            secret = bot_state["api_secret"].strip()
            if key and secret:
                try:
                    if not global_exchange:
                        global_exchange = ccxtpro.bybit({
                            'apiKey': key,
                            'secret': secret,
                            'enableRateLimit': True,
                            'options': {'defaultType': 'linear', 'adjustForTimeDifference': True}
                        })
                        if bot_state["is_demo"]:
                            global_exchange.set_sandbox_mode(True)
                        await global_exchange.load_markets()
                        bot_state["log"] = "Conexão Bybit HFT ativa."

                    # Atualizar saldo e tickers
                    bal = await global_exchange.fetch_balance()
                    total = float(bal.get('total', {}).get('USDT', 0.0))
                    if total > 0:
                        if bot_state["initial_balance"] == 0.0:
                            bot_state["initial_balance"] = total
                        bot_state["balance"] = total

                    # Executar motor de scalping
                    engine = ScalpingEngine(global_exchange, PAIRS, bot_state["leverage"])
                    await engine.execute_hft_loop(bot_state)

                except Exception as e:
                    bot_state["log"] = "Erro de conexão API. A tentar reconectar..."
                    global_exchange = None
                    await asyncio.sleep(3)
        else:
            if global_exchange:
                await global_exchange.close()
                global_exchange = None
            await asyncio.sleep(1)

def run_background_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_main_loop())

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BYBIT HFT SCALPING</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 8px 8px 75px 8px; }
        .container { max-width: 480px; margin: auto; }
        h1 { color: #f59e0b; text-align: center; font-size: 18px; margin: 8px 0; }
        .balance-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .balance-box { background: #1e293b; border: 1px solid #334155; padding: 10px; border-radius: 8px; text-align: center; }
        .balance-box span { display: block; font-size: 10px; color: #94a3b8; text-transform: uppercase; }
        .balance-box strong { font-size: 14px; color: #f59e0b; }
        .card { background: #1e293b; border: 1px solid #334155; padding: 12px; border-radius: 8px; margin-bottom: 10px; }
        .card h3 { color: #38bdf8; font-size: 12px; margin-top: 0; margin-bottom: 8px; text-transform: uppercase; }
        input[type="text"], input[type="password"], input[type="number"] { width: 100%; padding: 8px; margin: 4px 0 8px 0; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #fff; box-sizing: border-box; }
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #1e293b; border-top: 1px solid #334155; display: flex; justify-content: space-around; align-items: center; padding: 6px 0; height: 50px; z-index: 100; }
        .nav-btn { background: none; border: none; color: #94a3b8; font-size: 10px; font-weight: bold; cursor: pointer; flex: 1; text-align: center; }
        .nav-btn.active { color: #f59e0b; }
        .btn-circle { width: 44px; height: 44px; border-radius: 50%; border: none; display: flex; align-items: center; justify-content: center; font-size: 18px; cursor: pointer; color: white; }
        .btn-circle.start { background: #16a34a; }
        .btn-circle.stop { background: #dc2626; }
        .log-box { background: #0f172a; border-left: 3px solid #f59e0b; padding: 8px; font-size: 11px; color: #fde68a; max-height: 90px; overflow-y: auto; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
    </style>
    <script>
        function showTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            document.getElementById('btn-' + tabId).classList.add('active');
        }
        setInterval(() => {
            fetch('/api/state').then(res => res.json()).then(data => {
                if(data.log) document.querySelector('.log-box').innerText = data.log;
            });
        }, 2000);
    </script>
</head>
<body>
    <div class="container">
        <h1>BYBIT HFT SCALPING</h1>
        
        <div id="dashboard" class="tab-content active">
            <div class="balance-grid">
                <div class="balance-box"><span>Inicial</span><strong>+{{ "%.2f"|format(initial_balance) }}</strong></div>
                <div class="balance-box"><span>Disponível</span><strong>+{{ "%.2f"|format(balance) }}</strong></div>
            </div>
            <div class="card">
                <h3>Posição Ativa (HFT)</h3>
                {% if active_position %}
                    <p>Ativo: <b>{{ active_position.pair }}</b> | Lado: <b>{{ active_position.side.upper() }}</b></p>
                    <p>Stop Dinamite Ativo: <b>{{ 'SIM' if active_position.dynamite_active else 'NÃO' }}</b></p>
                {% else %}
                    <p style="color: #94a3b8; font-size: 12px; text-align: center;">À procura de oportunidade sem saturação...</p>
                {% endif %}
            </div>
            <div class="balance-grid">
                <div class="balance-box"><span>Status</span><strong style="color: {{ '#4ade80' if running else '#f87171' }};">{{ 'OPERANDO' if running else 'PARADO' }}</strong></div>
                <div class="balance-box"><span>PnL Realizado</span><strong>{{ "%.4f"|format(realized_pnl) }}</strong></div>
            </div>
            <div class="card">
                <h3>Log de Alta Frequência</h3>
                <div class="log-box">{{ log }}</div>
            </div>
        </div>

        <div id="ajustes" class="tab-content">
            <div class="card">
                <h3>Configuração API</h3>
                <form action="/settings" method="POST">
                    <label style="font-size: 11px; color: #94a3b8;">API Key:</label>
                    <input type="text" name="api_key" value="{{ api_key }}">
                    <label style="font-size: 11px; color: #94a3b8;">API Secret:</label>
                    <input type="password" name="api_secret" value="{{ api_secret }}">
                    <label style="font-size: 11px; color: #94a3b8;">Alavancagem:</label>
                    <input type="number" name="leverage" value="{{ leverage }}" min="1" max="50">
                    <button type="submit" style="width: 100%; padding: 10px; background: #f59e0b; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; margin-top: 8px;">Guardar</button>
                </form>
            </div>
        </div>

        <div class="nav-bar">
            <button id="btn-dashboard" class="nav-btn active" onclick="showTab('dashboard')">📊<br>Dashboard</button>
            <div style="flex:0; position:relative; bottom:10px;">
                <form action="/toggle" method="POST" style="margin:0;">
                    <button type="submit" class="btn-circle {{ 'stop' if running else 'start' }}">{{ '⏹' if running else '▶' }}</button>
                </form>
            </div>
            <button id="btn-ajustes" class="nav-btn" onclick="showTab('ajustes')">⚙️<br>Ajustes</button>
        </div>
    </div>
</body>
</html>
"""

@app.route('/api/state')
def api_state():
    return jsonify({"log": str(bot_state["log"])})

@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        running=bot_state["running"],
        initial_balance=bot_state["initial_balance"],
        balance=bot_state["balance"],
        realized_pnl=bot_state["realized_pnl"],
        active_position=bot_state["active_position"],
        api_key=bot_state["api_key"],
        api_secret=bot_state["api_secret"],
        leverage=bot_state["leverage"],
        log=bot_state["log"]
    )

@app.route('/settings', methods=['POST'])
def settings():
    global global_exchange
    global_exchange = None
    bot_state["api_key"] = request.form.get("api_key", "").strip()
    bot_state["api_secret"] = request.form.get("api_secret", "").strip()
    try:
        bot_state["leverage"] = int(request.form.get("leverage", 21))
    except:
        bot_state["leverage"] = 21
    bot_state["log"] = "Definições guardadas. Pronto a iniciar."
    return redirect(url_for('index'))

@app.route('/toggle', methods=['POST'])
def toggle():
    if not bot_state["api_key"] or not bot_state["api_secret"]:
        bot_state["log"] = "Erro: Insira as chaves API primeiro."
        return redirect(url_for('index'))
    bot_state["running"] = not bot_state["running"]
    bot_state["log"] = "Motor HFT iniciado." if bot_state["running"] else "Motor HFT parado."
    return redirect(url_for('index'))

if __name__ == '__main__':
    threading.Thread(target=run_background_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
