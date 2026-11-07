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
    "is_demo": True,
    "leverage": 21,
    "initial_balance": 1000.0,  # Valor padrão visível para testes
    "balance": 1000.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "market_data": [
        {"pair": "ADA", "price": "0.4500"},
        {"pair": "XRP", "price": "0.5500"},
        {"pair": "DOGE", "price": "0.1200"},
        {"pair": "TRX", "price": "0.1100"}
    ],
    "history": [],
    "last_update": "Aguardando...",
    "log": "Sistema Bybit pronto. Configure as chaves em Ajustes."
}

PAIRS = ['ADA/USDT:USDT', 'XRP/USDT:USDT', 'DOGE/USDT:USDT', 'TRX/USDT:USDT']
global_exchange = None

def get_exchange():
    global global_exchange
    key = str(bot_state["api_key"] or "").strip()
    secret = str(bot_state["api_secret"] or "").strip()

    if not key or not secret:
        return None

    if global_exchange is None:
        try:
            exchange = ccxt.bybit({
                'apiKey': key,
                'secret': secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'linear',
                    'adjustForTimeDifference': True
                }
            })
            
            if bot_state["is_demo"]:
                exchange.set_sandbox_mode(True)
                
            exchange.load_markets()
            global_exchange = exchange
            bot_state["log"] = "Conexão Bybit estabelecida com sucesso."
        except Exception as e:
            bot_state["log"] = "Erro de conexão Bybit. Verifique as chaves."
            global_exchange = None
    return global_exchange

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BYBIT SCALPING</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 8px 8px 75px 8px; }
        .container { max-width: 480px; margin: auto; }
        h1 { color: #f59e0b; text-align: center; font-size: 18px; margin: 8px 0 2px 0; font-weight: 700; }
        .clock { text-align: center; font-size: 11px; color: #38bdf8; margin-bottom: 10px; font-weight: bold; }
        
        .balance-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .balance-box { background: #1e293b; border: 1px solid #334155; padding: 10px; border-radius: 8px; text-align: center; }
        .balance-box span { display: block; font-size: 10px; color: #94a3b8; text-transform: uppercase; margin-bottom: 2px; }
        .balance-box strong { font-size: 14px; color: #f59e0b; }
        
        .card { background: #1e293b; border: 1px solid #334155; padding: 12px; border-radius: 8px; margin-bottom: 10px; }
        .card h3 { color: #38bdf8; font-size: 12px; margin-top: 0; margin-bottom: 8px; text-transform: uppercase; }
        
        input[type="text"], input[type="password"], input[type="number"] { width: 100% !important; padding: 8px; margin-top: 4px; margin-bottom: 8px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #fff; box-sizing: border-box; font-size: 14px; }
        .checkbox-container { display: flex; align-items: center; gap: 8px; margin: 8px 0; font-size: 13px; color: #cbd5e1; cursor: pointer; }
        
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #1e293b; border-top: 1px solid #334155; display: flex; justify-content: space-around; align-items: center; padding: 6px 0; z-index: 100; height: 50px; }
        .nav-btn { background: none; border: none; color: #94a3b8; font-size: 10px; font-weight: bold; cursor: pointer; text-align: center; flex: 1; }
        .nav-btn.active { color: #f59e0b; }
        
        .center-toggle-container { flex: 0; display: flex; justify-content: center; position: relative; bottom: 10px; }
        .btn-circle { width: 44px; height: 44px; border-radius: 50%; border: none; display: flex; align-items: center; justify-content: center; font-size: 18px; cursor: pointer; color: white; }
        .btn-circle.start { background: #16a34a; }
        .btn-circle.stop { background: #dc2626; }

        .log-box { background: #0f172a; border-left: 3px solid #f59e0b; padding: 8px; border-radius: 4px; font-size: 11px; color: #fde68a; word-break: break-all; max-height: 90px; overflow-y: auto; }
        .market-item { display: flex; justify-content: space-between; align-items: center; background: #334155; padding: 8px 10px; border-radius: 6px; margin-bottom: 6px; font-size: 13px; }
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
                    }).catch(err => {});
            }, 2000);
        }
    </script>
</head>
<body>
    <div class="container">
        <h1>BYBIT SCALPING</h1>
        <div class="clock">Sincronizado: {{ last_update }}</div>

        <!-- ABA DASHBOARD -->
        <div id="dashboard" class="tab-content active">
            <div class="balance-grid">
                <div class="balance-box">
                    <span>Inicial</span>
                    <strong>+{{ "%.2f"|format(initial_balance) }}</strong>
                </div>
                <div class="balance-box">
                    <span>Disponível ({{ 'TESTNET' if is_demo else 'REAL' }})</span>
                    <strong>+{{ "%.2f"|format(balance) }}</strong>
                </div>
            </div>

            <div class="card">
                <h3>Posição Ativa</h3>
                {% if active_position %}
                    <p>Ativo: <b>{{ active_position.pair }}</b></p>
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
            <div class="card">
                <h3>Mercado em Tempo Real</h3>
                {% for item in market_data %}
                <div class="market-item">
                    <div>
                        <b>{{ item.pair }}</b><br>
                        <span style="font-size: 12px; color: #cbd5e1;">{{ item.price }}</span>
                    </div>
                </div>
                {% else %}
                <p style="text-align: center; color: #94a3b8; font-size: 12px;">A carregar mercado...</p>
                {% endfor %}
            </div>
        </div>

        <!-- ABA HISTÓRICO -->
        <div id="historico" class="tab-content">
            <div class="card">
                <h3>Registo de Operações</h3>
                <p style="text-align: center; color: #94a3b8; font-size: 12px;">Nenhum registo recente.</p>
            </div>
        </div>

        <!-- ABA AJUSTES -->
        <div id="ajustes" class="tab-content">
            <div class="card">
                <h3>Configuração Bybit API</h3>
                <form action="/settings" method="POST">
                    <label style="font-size: 11px; color: #94a3b8;">API Key:</label>
                    <input type="text" name="api_key" value="{{ api_key }}">
                    
                    <label style="font-size: 11px; color: #94a3b8;">API Secret:</label>
                    <input type="text" name="api_secret" value="{{ api_secret }}">
                    
                    <label style="font-size: 11px; color: #94a3b8;">Alavancagem:</label>
                    <input type="number" name="leverage" value="{{ leverage }}" min="1" max="50" required>
                    
                    <label class="checkbox-container">
                        <input type="checkbox" name="is_demo" {% if is_demo %}checked{% endif %}>
                        Usar Testnet (Modo Demonstração)
                    </label>
                    
                    <button type="submit" style="width: 100%; padding: 10px; border-radius: 6px; border: none; font-size: 14px; font-weight: bold; cursor: pointer; background: #f59e0b; color: #0f172a; margin-top: 6px;">Guardar Definições</button>
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

def fetch_data():
    ex = get_exchange()
    if not ex:
        return
    try:
        bal = ex.fetch_balance()
        total = float(bal.get('total', {}).get('USDT', 0.0) or 0.0)
        if total > 0:
            if float(bot_state["initial_balance"]) == 1000.0:
                bot_state["initial_balance"] = total
            bot_state["balance"] = total

        m_list = []
        for sym in PAIRS:
            ticker = ex.fetch_ticker(sym)
            m_list.append({"pair": sym.split('/')[0], "price": ticker.get('last', 0.0)})
        bot_state["market_data"] = m_list
        bot_state["last_update"] = datetime.datetime.now().strftime("%H:%M:%S")
    except Exception:
        bot_state["log"] = "Erro de sincronização com a Bybit."

@app.route('/api/state')
def api_state():
    return jsonify({
        "log": str(bot_state["log"] or ""),
        "last_update": str(bot_state["last_update"] or "")
    })

@app.route('/')
def index():
    if bot_state["api_key"]:
        fetch_data()
    return render_template_string(
        HTML_TEMPLATE,
        running=bot_state["running"],
        initial_balance=float(bot_state["initial_balance"] or 1000.0),
        balance=float(bot_state["balance"] or 1000.0),
        realized_pnl=float(bot_state["realized_pnl"] or 0.0),
        active_position=bot_state["active_position"],
        market_data=bot_state["market_data"],
        history=bot_state["history"],
        api_key=str(bot_state["api_key"] or ""),
        api_secret=str(bot_state["api_secret"] or ""),
        leverage=int(bot_state["leverage"] or 21),
        is_demo=bool(bot_state["is_demo"]),
        last_update=str(bot_state["last_update"] or "Aguardando..."),
        log=str(bot_state["log"] or "Sistema pronto.")
    )

@app.route('/settings', methods=['POST'])
def settings():
    global global_exchange
    global_exchange = None
    
    bot_state["api_key"] = str(request.form.get("api_key") or "").strip()
    bot_state["api_secret"] = str(request.form.get("api_secret") or "").strip()
    bot_state["is_demo"] = True if request.form.get("is_demo") else False
    
    try:
        bot_state["leverage"] = int(request.form.get("leverage") or 21)
    except:
        bot_state["leverage"] = 21
    
    bot_state["log"] = "Definições guardadas. A ligar à Bybit..."
    return redirect(url_for('index'))

@app.route('/toggle', methods=['POST'])
def toggle():
    key = str(bot_state["api_key"] or "").strip()
    secret = str(bot_state["api_secret"] or "").strip()

    if not key or not secret:
        bot_state["log"] = "Erro: Insira as chaves Bybit em Ajustes!"
        return redirect(url_for('index'))
    
    bot_state["running"] = not bot_state["running"]
    mode_str = "TESTNET" if bot_state["is_demo"] else "REAL"
    bot_state["log"] = f"Robô ativado na Bybit ({mode_str})." if bot_state["running"] else "Robô parado."
    return redirect(url_for('index'))

def background_loop():
    global global_exchange
    while True:
        try:
            if bot_state["running"]:
                fetch_data()
        except Exception:
            global_exchange = None
        time.sleep(3)

if __name__ == '__main__':
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
