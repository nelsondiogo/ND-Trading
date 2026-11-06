import time
import threading
import logging
import ccxt
from flask import Flask, render_template_string, request

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
    "history": [
        {"pair": "ADA", "side": "LONG", "pnl_usdt": 0.0012, "pnl_pct": 0.93, "reason": "Trailing Stop Absoluto"},
        {"pair": "ALGO", "side": "SHORT", "pnl_usdt": -0.0003, "pnl_pct": -1.28, "reason": "Stop Loss Técnico"}
    ],
    "log": "Insira as chaves API na aba Ajustes para iniciar."
}

PAIRS = [
    'ADA/USDT:USDT',
    'TRX/USDT:USDT',
    'NEAR/USDT:USDT',
    'LTC/USDT:USDT',
    'XRP/USDT:USDT',
    'DOGE/USDT:USDT'
]

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ND-SCALPING Pro</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 10px 10px 70px 10px; }
        .container { max-width: 500px; margin: auto; }
        h1 { color: #4ade80; text-align: center; font-size: 22px; margin-bottom: 15px; }
        .balance-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px; }
        .balance-box { background: #1e293b; border: 1px solid #334155; padding: 12px; border-radius: 10px; text-align: center; }
        .balance-box span { display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; margin-bottom: 4px; }
        .balance-box strong { font-size: 16px; color: #4ade80; }
        .card { background: #1e293b; border: 1px solid #334155; padding: 15px; border-radius: 12px; margin-bottom: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.2); }
        .card h3 { color: #38bdf8; font-size: 14px; margin-top: 0; margin-bottom: 10px; text-transform: uppercase; }
        button, input[type="submit"] { width: 100%; padding: 12px; border-radius: 8px; border: none; font-size: 16px; font-weight: bold; cursor: pointer; }
        .btn-start { background: #16a34a; color: white; }
        .btn-stop { background: #dc2626; color: white; }
        input[type="text"], input[type="password"], input[type="number"] { width: 100%; padding: 10px; margin-top: 5px; margin-bottom: 12px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #fff; box-sizing: border-box; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #1e293b; border-top: 1px solid #334155; display: flex; justify-content: space-around; padding: 10px 0; z-index: 100; }
        .nav-btn { background: none; border: none; color: #94a3b8; font-size: 12px; font-weight: bold; cursor: pointer; text-align: center; }
        .nav-btn.active { color: #4ade80; }
        .log-box { background: #0f172a; border-left: 4px solid #4ade80; padding: 10px; border-radius: 6px; font-size: 13px; color: #cbd5e1; }
        .market-item { display: flex; justify-content: space-between; align-items: center; background: #334155; padding: 10px; border-radius: 8px; margin-bottom: 8px; }
        .history-item { background: #334155; padding: 10px; border-radius: 8px; margin-bottom: 8px; font-size: 13px; display: flex; justify-content: space-between; align-items: center; }
    </style>
    <script>
        function showTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            document.getElementById('btn-' + tabId).classList.add('active');
        }
    </script>
    <meta http-equiv="refresh" content="15">
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
            <div class="card" style="border-left: 4px solid #f87171; text-align: center;">
                <p style="color: #f87171; margin: 0; font-weight: bold;">Chaves API em falta!</p>
                <small style="color: #94a3b8;">Vá à aba Ajustes para configurar a sua conta.</small>
            </div>
            {% endif %}

            <div class="card">
                <h3>Estado da Posição</h3>
                {% if active_position %}
                    <p>Ativo: <b>{{ active_position.pair }}</b> ({{ active_position.side }})</p>
                    <p>Entrada: <b>{{ active_position.entry }}</b></p>
                {% else %}
                    <p style="text-align: center; color: #94a3b8;">Nenhuma posição ativa no momento.</p>
                {% endif %}
            </div>

            <div class="card">
                <h3>Alavancagem & Capital</h3>
                <p>Alavancagem: <b>{{ leverage }}x</b></p>
                <p>Poder de Compra: <b>+{{ "%.6f"|format(balance * leverage) }} USDT</b></p>
            </div>

            <div class="balance-grid">
                <div class="balance-box">
                    <span>Status</span>
                    <strong style="color: {{ '#4ade80' if running else '#f87171' }}">{{ 'OPERANDO' if running else 'PARADO' }}</strong>
                </div>
                <div class="balance-box">
                    <span>PNL Realizado</span>
                    <strong>{{ "%.6f"|format(realized_pnl) }}</strong>
                </div>
            </div>

            <div class="card">
                <h3>Estado / Log da API</h3>
                <div class="log-box">{{ log }}</div>
            </div>

            <form action="/toggle" method="POST">
                <button type="submit" class="{{ 'btn-stop' if running else 'btn-start' }}">
                    {{ 'PARAR ROBÔ' if running else 'INICIAR ROBÔ' }}
                </button>
            </form>
        </div>

        <!-- ABA MERCADO -->
        <div id="mercado" class="tab-content">
            {% if configured %}
            <div class="balance-grid" style="margin-bottom: 15px;">
                <div class="balance-box">
                    <span>Saldo Disponível</span>
                    <strong>+{{ "%.6f"|format(balance) }} USDT</strong>
                </div>
                <div class="balance-box">
                    <span>Ativos Monitorizados</span>
                    <strong style="color: #38bdf8;">{{ market_data|length }} Pares</strong>
                </div>
            </div>
            {% endif %}

            <div class="card">
                <h3>Mercado Scalping (Tempo Real)</h3>
                {% for item in market_data %}
                <div class="market-item">
                    <div>
                        <b>{{ item.pair }}</b><br>
                        <small style="color: #94a3b8;">Preço: {{ item.price }} | RSI: {{ "%.1f"|format(item.rsi) }}</small>
                    </div>
                    <span style="color: {{ '#4ade80' if item.trend == 'LONG' else ('#f87171' if item.trend == 'SHORT' else '#94a3b8') }}; font-weight: bold;">
                        {{ item.trend }}
                    </span>
                </div>
                {% else %}
                <p style="text-align: center; color: #94a3b8;">{{ 'Configure as chaves API para carregar o mercado.' if not configured else 'A carregar dados da Bybit...' }}</p>
                {% endfor %}
            </div>
        </div>

        <!-- ABA HISTÓRICO -->
        <div id="historico" class="tab-content">
            <div class="card">
                <h3>Resumo Geral do Histórico</h3>
                {% set total_trades = history|length %}
                {% set pos_count = namespace(val=0) %}
                {% set neg_count = namespace(val=0) %}
                {% set total_usdt = namespace(val=0.0) %}
                
                {% for h in history %}
                    {% set total_usdt.val = total_usdt.val + h.pnl_usdt %}
                    {% if h.pnl_usdt >= 0 %}
                        {% set pos_count.val = pos_count.val + 1 %}
                    {% else %}
                        {% set neg_count.val = neg_count.val + 1 %}
                    {% endif %}
                {% endfor %}

                <p>Total de Operações: <b>{{ total_trades }}</b></p>
                <p>Operações Positivas: <b style="color: #4ade80;">{{ pos_count.val }}</b> | Negativas: <b style="color: #f87171;">{{ neg_count.val }}</b></p>
                <p>Resultado Geral (USDT): <b style="color: {{ '#4ade80' if total_usdt.val >= 0 else '#f87171' }}">{{ "%.4f"|format(total_usdt.val) }} USDT</b></p>
            </div>

            <div class="card">
                <h3>Registo de Operações</h3>
                {% for h in history %}
                <div class="history-item">
                    <div>
                        <b>{{ h.pair }} ({{ h.side }})</b><br>
                        <small style="color: #94a3b8;">{{ h.reason }}</small>
                    </div>
                    <div style="text-align: right;">
                        <span style="color: {{ '#4ade80' if h.pnl_usdt >= 0 else '#f87171' }}; font-weight: bold;">
                            {{ "+%.4f"|format(h.pnl_usdt) if h.pnl_usdt >= 0 else "%.4f"|format(h.pnl_usdt) }} USDT
                        </span><br>
                        <small style="color: {{ '#4ade80' if h.pnl_pct >= 0 else '#f87171' }};">
                            {{ "+%.2f"|format(h.pnl_pct) if h.pnl_pct >= 0 else "%.2f"|format(h.pnl_pct) }}%
                        </small>
                    </div>
                </div>
                {% else %}
                <p style="text-align: center; color: #94a3b8;">Nenhum registo de histórico recente.</p>
                {% endfor %}
            </div>
        </div>

        <!-- ABA AJUSTES -->
        <div id="ajustes" class="tab-content">
            <div class="card">
                <h3>Configuração & Alavancagem</h3>
                <form action="/settings" method="POST">
                    <label>Bybit API Key:</label>
                    <input type="text" name="api_key" value="{{ api_key }}" required>
                    
                    <label>Bybit API Secret:</label>
                    <input type="password" name="api_secret" value="{{ api_secret }}" required>
                    
                    <label>Alavancagem Manual:</label>
                    <input type="number" name="leverage" value="{{ leverage }}" min="1" max="50" required>
                    
                    <button type="submit" class="btn-start" style="margin-top: 10px;">Guardar Definições</button>
                </form>
            </div>
        </div>

        <!-- BARRA DE NAVEGAÇÃO INFERIOR -->
        <div class="nav-bar">
            <button id="btn-dashboard" class="nav-btn active" onclick="showTab('dashboard')">📊 Dashboard</button>
            <button id="btn-mercado" class="nav-btn" onclick="showTab('mercado')">📈 Mercado</button>
            <button id="btn-historico" class="nav-btn" onclick="showTab('historico')">📋 Histórico</button>
            <button id="btn-ajustes" class="nav-btn" onclick="showTab('ajustes')">⚙️ Ajustes</button>
        </div>
    </div>
</body>
</html>
"""

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
    if key:
        bot_state["api_key"] = key
    if secret and secret != "********":
        bot_state["api_secret"] = secret
    try:
        bot_state["leverage"] = int(request.form.get("leverage", 17))
    except ValueError:
        pass
    
    bot_state["log"] = "Definições e alavancagem atualizadas com sucesso."
    return index()

@app.route('/toggle', methods=['POST'])
def toggle():
    if not bot_state["api_key"] or not bot_state["api_secret"]:
        bot_state["log"] = "Erro: Insira as chaves API nos Ajustes primeiro!"
        return index()
    
    bot_state["running"] = not bot_state["running"]
    bot_state["log"] = "ND-SCALPING Ativo e ligado à corretora." if bot_state["running"] else "Robô parado manualmente."
    return index()

def background_loop():
    while True:
        try:
            if bot_state["api_key"] and bot_state["api_secret"]:
                exchange = ccxt.bybit({
                    'apiKey': bot_state["api_key"],
                    'secret': bot_state["api_secret"],
                    'enableRateLimit': True,
                    'options': {'defaultType': 'swap'}
                })
                
                # Ler saldo real da Bybit
                bal = exchange.fetch_balance()
                total = float(bal.get('total', {}).get('USDT', 0.0))
                if total > 0:
                    if bot_state["initial_balance"] == 0.0:
                        bot_state["initial_balance"] = total
                    bot_state["balance"] = total

                # Ler mercado e indicadores RSI
                market_list = []
                for pair in PAIRS:
                    ticker = exchange.fetch_ticker(pair)
                    price = ticker.get('last', 0.0)
                    
                    ohlcv = exchange.fetch_ohlcv(pair, timeframe='1m', limit=20)
                    if ohlcv and len(ohlcv) >= 14:
                        closes = [candle[4] for candle in ohlcv]
                        gains, losses = 0.0, 0.0
                        for i in range(1, len(closes)):
                            diff = closes[i] - closes[i-1]
                            if diff > 0: gains += diff
                            else: losses -= diff
                        rs = (gains / 14) / ((losses / 14) if losses != 0 else 1)
                        rsi = 100 - (100 / (1 + rs))
                    else:
                        rsi = 50.0

                    if rsi < 35:
                        trend = "LONG"
                    elif rsi > 65:
                        trend = "SHORT"
                    else:
                        trend = "NEUTRO"

                    market_list.append({
                        "pair": pair.split('/')[0],
                        "price": price,
                        "rsi": rsi,
                        "trend": trend
                    })
                
                bot_state["market_data"] = market_list

        except Exception as e:
            logging.error(f"Erro na ligação à Bybit: {e}")
            bot_state["log"] = f"Erro de leitura API: {str(e)[:50]}"
        
        time.sleep(10)

if __name__ == '__main__':
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
