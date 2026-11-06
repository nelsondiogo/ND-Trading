import time
import threading
import logging
import ccxt
from flask import Flask, render_template_string, request, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

app = Flask(__name__)

# Estado do Robô
bot_state = {
    "running": False,
    "api_key": "",
    "api_secret": "",
    "balance": 0.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "log": "Robô pronto a iniciar.",
    "history": []
}

PAIRS = ['ADA/USDT:USDT', 'TRX/USDT:USDT', 'NEAR/USDT:USDT', 'LTC/USDT:USDT']

# Interface Visual em HTML integrada para facilitar o uso no telemóvel/PC
HTML_PAGE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ND-SCALPING Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .container { max-width: 600px; margin: auto; background: #1e293b; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        hh1, h2 { color: #38bdf8; text-align: center; }
        .card { background: #334155; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
        input, button { width: 100%%; padding: 10px; margin-top: 8px; border-radius: 6px; border: none; font-size: 16px; box-sizing: border-box; }
        input { background: #1e293b; color: #fff; border: 1px solid #475569; }
        button { background: #0284c7; color: white; font-weight: bold; cursor: pointer; }
        button:hover { background: #0ea5e9; }
        .btn-stop { background: #dc2626; }
        .btn-stop:hover { background: #ef4444; }
        .status-on { color: #4ade80; font-weight: bold; }
        .status-off { color: #f87171; font-weight: bold; }
        pre { background: #0f172a; padding: 10px; border-radius: 6px; overflow-x: auto; font-size: 13px; color: #38bdf8; }
    </style>
</head>
<body>
    <div class="container">
        <h1>ND-SCALPING</h1>
        <div class="card">
            <h3>Estado do Sistema</h3>
            <p>Estado: <span id="bot-status" class="{{ 'status-on' if running else 'status-off' }}">{{ 'ATIVO' if running else 'PARADO' }}</span></p>
            <p>Saldo USDT: <span id="bot-balance">{{ balance }}</span></p>
            <p>Log: <span id="bot-log">{{ log }}</span></p>
        </div>

        <div class="card">
            <h3>Controlo</h3>
            <form action="/toggle" method="POST">
                <button type="submit" class="{{ 'btn-stop' if running else '' }}">{{ 'Desligar Robô' if running else 'Ligar Robô' }}</button>
            </form>
        </div>

        <div class="card">
            <h3>Configurar Chaves API (Bybit)</h3>
            <form action="/settings" method="POST">
                <label>API Key:</label>
                <input type="text" name="api_key" value="{{ api_key }}" required>
                <label>API Secret:</label>
                <input type="password" name="api_secret" value="{{ api_secret }}" required>
                <button type="submit" style="background: #16a34a; margin-top: 15px;">Guardar Chaves</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(
        HTML_PAGE,
        running=bot_state["running"],
        balance=bot_state["balance"],
        log=bot_state["log"],
        api_key=bot_state["api_key"],
        api_secret="" if not bot_state["api_secret"] else "********"
    )

@app.route('/settings', methods=['POST'])
def settings():
    bot_state["api_key"] = request.form.get("api_key", "").strip()
    secret = request.form.get("api_secret", "").strip()
    if secret and secret != "********":
        bot_state["api_secret"] = secret
    bot_state["log"] = "Chaves atualizadas com sucesso!"
    return index()

@app.route('/toggle', methods=['POST'])
def toggle():
    if not bot_state["api_key"] or not bot_state["api_secret"]:
        bot_state["log"] = "Erro: Insira as chaves API primeiro!"
        return index()
    
    bot_state["running"] = not bot_state["running"]
    bot_state["log"] = "Robô ativado com sucesso." if bot_state["running"] else "Robô parado."
    return index()

# Loop de fundo para simular e negociar
def background_loop():
    while True:
        try:
            if bot_state["running"] and bot_state["api_key"]:
                exchange = ccxt.bybit({
                    'apiKey': bot_state["api_key"],
                    'secret': bot_state["api_secret"],
                    'enableRateLimit': True,
                    'options': {'defaultType': 'swap'}
                })
                bal = exchange.fetch_balance()
                total = float(bal.get('total', {}).get('USDT', 0.0))
                if total > 0:
                    bot_state["balance"] = total
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
        time.sleep(5)

if __name__ == '__main__':
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
