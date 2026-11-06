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
    "balance": 0.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "market_data": [],
    "log": "Sistema operacional e pronto.",
    "history": []
}

PAIRS = ['ADA/USDT:USDT', 'TRX/USDT:USDT', 'NEAR/USDT:USDT', 'LTC/USDT:USDT']

HTML_PAGE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ND-SCALPING Pro</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 15px; }
        .container { max-width: 650px; margin: auto; background: #1e293b; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        h1, h3 { color: #38bdf8; text-align: center; }
        .card { background: #334155; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
        input, button { width: 100%; padding: 10px; margin-top: 8px; border-radius: 6px; border: none; font-size: 15px; box-sizing: border-box; }
        input { background: #1e293b; color: #fff; border: 1px solid #475569; }
        button { background: #0284c7; color: white; font-weight: bold; cursor: pointer; }
        button:hover { background: #0ea5e9; }
        .btn-stop { background: #dc2626; }
        .btn-stop:hover { background: #ef4444; }
        .status-on { color: #4ade80; font-weight: bold; }
        .status-off { color: #f87171; font-weight: bold; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #475569; }
        th { color: #38bdf8; }
    </style>
    <meta http-equiv="refresh" content="10">
</head>
<body>
    <div class="container">
        <h1>ND-SCALPING Pro</h1>
        
        <div class="card">
            <h3>Estado do Sistema</h3>
            <p>Estado: <span class="{{ 'status-on' if running else 'status-off' }}">{{ 'ATIVO (A negociar)' if running else 'PARADO' }}</span></p>
            <p>Saldo Total: <b>{{ "%.4f"|format(balance) }} USDT</b></p>
            <p>Log: {{ log }}</p>
        </div>

        <div class="card">
            <h3>Controlo do Robô</h3>
            <form action="/toggle" method="POST">
                <button type="submit" class="{{ 'btn-stop' if running else '' }}">{{ 'Desligar Robô' if running else 'Ligar Robô' }}</button>
            </form>
        </div>

        <div class="card">
            <h3>Mercado em Tempo Real</h3>
            <table>
                <tr>
                    <th>Par</th>
                    <th>Preço (USDT)</th>
                    <th>RSI</th>
                    <th>Tendência</th>
                </tr>
                {% for item in market_data %}
                <tr>
                    <td><b>{{ item.pair }}</b></td>
                    <td>{{ item.price }}</td>
                    <td>{{ "%.1f"|format(item.rsi) }}</td>
                    <td><span style="color: {{ '#4ade80' if item.trend == 'LONG' else '#f87171' }}">{{ item.trend }}</span></td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="4" style="text-align: center; color: #94a3b8;">Ligue o robô ou insira as chaves para carregar o mercado.</td>
                </tr>
                {% endfor %}
            </table>
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
        market_data=bot_state["market_data"],
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
    bot_state["log"] = "Robô ativado e a monitorizar o mercado." if bot_state["running"] else "Robô parado."
    return index()

def background_loop():
    while True:
        try:
            if bot_state["api_key"]:
                exchange = ccxt.bybit({
                    'apiKey': bot_state["api_key"],
                    'secret': bot_state["api_secret"],
                    'enableRateLimit': True,
                    'options': {'defaultType': 'swap'}
                })
                
                # Ler Saldo Real
                bal = exchange.fetch_balance()
                total = float(bal.get('total', {}).get('USDT', 0.0))
                if total > 0:
                    bot_state["balance"] = total

                # Ler Mercado e calcular RSI em tempo real
                market_list = []
                for pair in PAIRS:
                    ticker = exchange.fetch_ticker(pair)
                    price = ticker.get('last', 0.0)
                    
                    # Buscar velas para cálculo do RSI
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

                    trend = "LONG" if rsi < 50 else "SHORT"
                    market_list.append({
                        "pair": pair.split('/')[0],
                        "price": price,
                        "rsi": rsi,
                        "trend": trend
                    })
                
                bot_state["market_data"] = market_list

        except Exception as e:
            logging.error(f"Erro no loop de mercado: {e}")
        
        time.sleep(10)

if __name__ == '__main__':
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
