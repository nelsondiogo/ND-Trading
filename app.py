import time
import threading
import datetime
from flask import Flask, render_template_string, request, redirect, url_for, jsonify
from config import PAIRS, LEVERAGE_DEFAULT
from exchange_management import get_exchange
from trading import execute_trading_logic

app = Flask(__name__)

bot_state = {
    "running": False,
    "api_key": "",
    "api_secret": "",
    "is_demo": True,
    "leverage": LEVERAGE_DEFAULT,
    "initial_balance": 0.0,
    "balance": 0.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "market_data": [],
    "history": [],
    "last_update": "Aguardando...",
    "log": "ND-SCALPING Ativo (Versão Estável 05h-07h)!"
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ND-SCALPING</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding: 12px 12px 80px 12px; }
        .container { max-width: 480px; margin: auto; }
        h1 { color: #22c55e; text-align: center; font-size: 16px; margin: 4px 0 2px 0; font-weight: 800; letter-spacing: 1.5px; }
        .clock { text-align: center; font-size: 11px; color: #38bdf8; margin-bottom: 12px; font-weight: bold; }
        
        .balance-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .balance-box { background: #131b2e; border: 1px solid #1e293b; padding: 12px 8px; border-radius: 8px; text-align: center; }
        .balance-box span { display: block; font-size: 9px; color: #64748b; text-transform: uppercase; margin-bottom: 4px; font-weight: 700; }
        .balance-box strong { font-size: 14px; color: #22c55e; }
        
        .card { background: #131b2e; border: 1px solid #1e293b; padding: 14px; border-radius: 8px; margin-bottom: 10px; }
        .card h3 { color: #38bdf8; font-size: 11px; margin-top: 0; margin-bottom: 10px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px; }
        
        label { font-size: 12px; color: #38bdf8; font-weight: 600; display: block; margin-top: 8px; }
        input[type="text"], input[type="number"] { width: 100% !important; padding: 10px; margin-top: 6px; margin-bottom: 10px; border-radius: 6px; border: 1px solid #1e293b; background: #0b0f19; color: #fff; box-sizing: border-box; font-size: 13px; }
        input[type="password"] { width: 100% !important; padding: 10px; margin-top: 6px; margin-bottom: 10px; border-radius: 6px; border: 1px solid #1e293b; background: #0b0f19; color: #fff; box-sizing: border-box; font-size: 11px; letter-spacing: 3px; text-overflow: ellipsis; }
        
        .checkbox-container { display: flex; align-items: center; gap: 8px; margin: 12px 0 16px 0; font-size: 13px; color: #cbd5e1; cursor: pointer; }
        
        .btn-action { width: 100%; padding: 14px; border-radius: 8px; border: none; font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; cursor: pointer; color: #ffffff; }
        .btn-action.start { background: #22c55e; }
        .btn-action.stop { background: #ef4444; }
        .btn-save { width: 100%; padding: 12px; border-radius: 6px; border: none; font-size: 13px; font-weight: bold; cursor: pointer; background: #0284c7; color: #ffffff; margin-top: 6px; }

        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #0b0f19; border-top: 1px solid #1e293b; display: flex; justify-content: space-around; align-items: center; padding: 8px 0; z-index: 100; height: 52px; }
        .nav-btn { background: none; border: none; color: #64748b; font-size: 10px; font-weight: bold; cursor: pointer; text-align: center; flex: 1; }
        .nav-btn.active { color: #22c55e; }
        
        .log-box { background: #0b0f19; border-left: 3px solid #22c55e; padding: 10px; border-radius: 4px; font-size: 11px; color: #22c55e; font-weight: 600; word-break: break-all; }
        .market-item { display: flex; justify-content: space-between; align-items: center; background: #0b0f19; padding: 10px 12px; border-radius: 6px; margin-bottom: 8px; border: 1px solid #1e293b; }
        .badge-neutral { background: #1e293b; color: #94a3b8; font-size: 10px; padding: 3px 8px; border-radius: 4px; font-weight: bold; }
        p { margin: 4px 0; font-size: 13px; }
    </style>
    <script>
        function showTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            if(document.getElementById('btn-' + tabId)) {
                document.getElementById('btn-' + tabId).classList.add('active');
            }
            localStorage.setItem('activeNdTab', tabId);
        }
        window.onload = function() {
            let savedTab = localStorage.getItem('activeNdTab');
            if (savedTab && document.getElementById(savedTab)) {
                showTab(savedTab);
            }
            setInterval(function() {
                fetch('/api/state')
                    .then(response => response.json())
                    .then(data => {
                        if(data.log) { let l = document.querySelector('.log-box'); if(l) l.innerText = data.log; }
                        if(data.last_update) { let c = document.querySelector('.clock'); if(c) c.innerText = "Sincronizado: " + data.last_update; }
                    });
            }, 2000);
        }
    </script>
</head>
<body>
    <div class="container">
        <h1>ND-SCALPING</h1>
        <div class="clock">Sincronizado: {{ last_update }}</div>

        <div id="dashboard" class="tab-content active">
            <div class="balance-grid">
                <div class="balance-box"><span>INICIAL</span><strong>+{{ "%.6f"|format(initial_balance) }}</strong></div>
                <div class="balance-box"><span>ATUAL</span><strong>+{{ "%.6f"|format(balance) }}</strong></div>
            </div>
            
            <div class="card">
                <p style="text-align: center; color: #94a3b8; font-size: 12px; margin: 12px 0;">
                    {% if active_position %}
                        Ativo em Operação: <b>{{ active_position.pair }}</b>
                    {% else %}
                        Nenhuma posição ativa no momento.
                    {% endif %}
                </p>
            </div>

            <div class="card">
                <h3 style="color: #38bdf8;">ALAVANCAGEM CONFIGURADA: {{ leverage }}x</h3>
                <p style="font-size: 12px; color: #cbd5e1;">Poder de Compra: <b>+{{ "%.6f"|format(balance * leverage) }} USDT</b></p>
            </div>

            <div class="balance-grid">
                <div class="balance-box">
                    <span>STATUS</span>
                    <strong style="color: {{ '#22c55e' if running else '#ef4444' }}; font-size: 12px;">{{ 'OPERANDO' if running else 'PARADO' }}</strong>
                </div>
                <div class="balance-box">
                    <span>PNL REALIZADO</span>
                    <strong style="font-size: 12px; color: {{ '#22c55e' if realized_pnl >= 0 else '#ef4444' }}">{{ "%.6f"|format(realized_pnl) }}</strong>
                </div>
            </div>

            <div class="card">
                <h3>ESTADO / LOG DA API:</h3>
                <div class="log-box">{{ log }}</div>
            </div>

            <form action="/toggle" method="POST" style="margin-top: 15px;">
                <button type="submit" class="btn-action {{ 'stop' if running else 'start' }}">
                    {{ 'PARAR ROBÔ' if running else 'INICIAR ROBÔ' }}
                </button>
            </form>
        </div>

        <div id="mercado" class="tab-content">
            <div class="card">
                <h3>MERCADO SCALPING (6 ATIVOS)</h3>
                {% if market_data %}
                    {% for item in market_data %}
                    <div class="market-item">
                        <div>
                            <b style="font-size: 14px;">{{ item.pair }}</b><br>
                            <span style="font-size: 11px; color: #94a3b8;">Preço: {{ item.price }} | RSI: {{ item.rsi }}</span>
                        </div>
                        <span class="badge-neutral">{{ item.status }}</span>
                    </div>
                    {% endfor %}
                {% else %}
                    <p style="text-align: center; color: #94a3b8; font-size: 12px;">A carregar cotações...</p>
                {% endif %}
            </div>
        </div>

        <div id="historico" class="tab-content">
            <div class="card">
                <h3>REGISTO DE TRADES</h3>
                <p style="text-align: center; color: #94a3b8; font-size: 12px; margin: 20px 0;">Nenhuma operação fechada ainda.</p>
            </div>
        </div>

        <div id="ajustes" class="tab-content">
            <div class="card">
                <h3 style="color: #38bdf8; margin-bottom: 15px;">Configuração & Alavancagem</h3>
                <form action="/settings" method="POST">
                    <label>Bybit API Key:</label>
                    <input type="text" name="api_key" value="{{ api_key }}">
                    
                    <label>Bybit API Secret:</label>
                    <input type="password" name="api_secret" value="{{ api_secret }}">
                    
                    <label>Alavancagem Manual:</label>
                    <input type="number" name="leverage" value="{{ leverage }}" min="1" max="50" required>
                    
                    <label class="checkbox-container">
                        <input type="checkbox" name="is_demo" {% if is_demo %}checked{% endif %}> Ativar Testnet
                    </label>
                    
                    <button type="submit" class="btn-save">Guardar Definições</button>
                </form>
            </div>
        </div>

        <div class="nav-bar">
            <button id="btn-dashboard" class="nav-btn active" onclick="showTab('dashboard')">📊<br>Dashboard</button>
            <button id="btn-mercado" class="nav-btn" onclick="showTab('mercado')">📈<br>Mercado</button>
            <button id="btn-historico" class="nav-btn" onclick="showTab('historico')">📋<br>Histórico</button>
            <button id="btn-ajustes" class="nav-btn" onclick="showTab('ajustes')">⚙️<br>Ajustes</button>
        </div>
    </div>
</body>
</html>
"""

@app.route('/api/state')
def api_state():
    return jsonify({
        "log": str(bot_state["log"]),
        "last_update": str(bot_state["last_update"])
    })

@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        running=bot_state["running"],
        initial_balance=float(bot_state["initial_balance"]),
        balance=float(bot_state["balance"]),
        realized_pnl=float(bot_state["realized_pnl"]),
        active_position=bot_state["active_position"],
        market_data=bot_state["market_data"],
        history=bot_state["history"],
        api_key=str(bot_state["api_key"]),
        api_secret=str(bot_state["api_secret"]),
        leverage=int(bot_state["leverage"]),
        is_demo=bool(bot_state["is_demo"]),
        last_update=str(bot_state["last_update"]),
        log=str(bot_state["log"])
    )

@app.route('/settings', methods=['POST'])
def settings():
    bot_state["api_key"] = str(request.form.get("api_key")).strip()
    bot_state["api_secret"] = str(request.form.get("api_secret")).strip()
    bot_state["is_demo"] = True if request.form.get("is_demo") else False
    try:
        bot_state["leverage"] = int(request.form.get("leverage"))
    except:
        bot_state["leverage"] = LEVERAGE_DEFAULT
    bot_state["log"] = "Definições guardadas com sucesso."
    return redirect(url_for('index'))

@app.route('/toggle', methods=['POST'])
def toggle():
    if not bot_state["api_key"] or not bot_state["api_secret"]:
        bot_state["log"] = "Erro: Insira as chaves Bybit em Ajustes!"
        return redirect(url_for('index'))
    bot_state["running"] = not bot_state["running"]
    bot_state["log"] = "ND-SCALPING Ativo (Versão Estável 05h-07h)!" if bot_state["running"] else "ND-SCALPING parado manualmente."
    return redirect(url_for('index'))

def background_loop():
    global_exchange = None
    while True:
        try:
            if bot_state["running"]:
                if not global_exchange:
                    global_exchange = get_exchange(bot_state)
                
                if global_exchange:
                    execute_trading_logic(global_exchange, bot_state)
                    bot_state["last_update"] = datetime.datetime.now().strftime("%H:%M:%S")
            else:
                global_exchange = None
        except Exception:
            global_exchange = None
        time.sleep(3)

if __name__ == '__main__':
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
