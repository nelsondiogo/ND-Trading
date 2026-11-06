import time
import threading
import logging
import ccxt
from flask import Flask, render_template, request, jsonify
from config import load_config, save_config, PAIRS, are_keys_configured
from trading_engine import TradingEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

app = Flask(__name__)
config = load_config()
engine = TradingEngine(config)

bot_state = {
    "running": False,
    "balance": 0.0,
    "initial_balance": 0.0,
    "trades_history": [],
    "market_data": []
}

def get_exchange_client():
    cfg = load_config()
    if not cfg["configured"]:
        return None
    try:
        exchange = ccxt.bybit({
            'apiKey': cfg["BYBIT_API_KEY"],
            'secret': cfg["BYBIT_API_SECRET"],
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        if cfg["IS_TESTNET"]:
            exchange.set_sandbox_mode(True)
        return exchange
    except Exception as e:
        logging.error(f"Erro ao inicializar cliente Bybit: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    if not are_keys_configured():
        return jsonify({
            "configured": False,
            "running": False,
            "balance": 0.0,
            "initial_balance": 0.0,
            "market": [],
            "message": "Insira as chaves API em Ajustes."
        })

    exchange = get_exchange_client()
    balance_val = 0.0
    market_list = []

    if exchange:
        try:
            # Obter saldo real de USDT na conta de futuros/derivatives
            bal = exchange.fetch_balance()
            balance_val = float(bal.get('USDT', {}).get('free', 0.0))
            if balance_val == 0.0:
                balance_val = float(bal.get('total', {}).get('USDT', 0.0))

            # Obter preços reais do mercado
            for pair in PAIRS:
                ticker = exchange.fetch_ticker(pair)
                price = ticker.get('last', 0.0)
                market_list.append({
                    "pair": pair.split('/')[0],
                    "price": price,
                    "rsi": 50.0,  # Calculado pelo engine se necessário
                    "trend": "NEUTRO"
                })
        except Exception as e:
            logging.error(f"Erro ao buscar dados da corretora: {e}")

    if bot_state["initial_balance"] == 0.0 and balance_val > 0:
        bot_state["initial_balance"] = balance_val

    return jsonify({
        "configured": True,
        "running": bot_state["running"],
        "balance": balance_val if balance_val > 0 else bot_state["balance"],
        "initial_balance": bot_state["initial_balance"] if bot_state["initial_balance"] > 0 else 0.330964,
        "market": market_list,
        "pairs": PAIRS
    })

@app.route('/api/toggle', methods=['POST'])
def toggle_bot():
    if not are_keys_configured():
        return jsonify({"error": "Configure as chaves API primeiro."}), 400

    bot_state["running"] = not bot_state["running"]
    return jsonify({"running": bot_state["running"]})

@app.route('/api/settings', methods=['POST'])
def update_settings():
    data = request.json
    save_config(
        api_key=data.get("api_key", ""),
        api_secret=data.get("api_secret", ""),
        is_testnet=data.get("is_testnet", False),
        leverage=int(data.get("leverage", 17))
    )
    return jsonify({"status": "success", "message": "Definições e chaves guardadas com sucesso."})

def background_trading_loop():
    while True:
        try:
            if bot_state["running"] and are_keys_configured():
                exchange = get_exchange_client()
                if exchange:
                    # Execução do motor de scalping nos 4 pares
                    for pair in PAIRS:
                        ohlcv = exchange.fetch_ohlcv(pair, timeframe='1m', limit=50)
                        indicators = engine.calculate_indicators(ohlcv)
                        signal = engine.evaluate_signal(indicators)
                        if signal:
                            logging.info(f"Sinal detetado em {pair}: {signal}")
        except Exception as e:
            logging.error(f"Erro no loop de trading: {e}")
        time.sleep(3)

if __name__ == '__main__':
    t = threading.Thread(target=background_trading_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
