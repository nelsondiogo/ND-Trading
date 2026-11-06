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
    "balance": 0.2548,
    "initial_balance": 0.2548,
    "trades_history": [],
    "active_position": None  # None se não houver operação ativa
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
        logging.error(f"Erro ao inicializar Bybit: {e}")
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
            "active_position": None,
            "message": "Aguardando chaves API."
        })

    exchange = get_exchange_client()
    balance_val = 0.2548
    market_list = []

    if exchange:
        try:
            bal = exchange.fetch_balance()
            free_bal = float(bal.get('USDT', {}).get('free', 0.0))
            total_bal = float(bal.get('total', {}).get('USDT', 0.0))
            if total_bal > 0:
                balance_val = total_bal
            elif free_bal > 0:
                balance_val = free_bal

            for pair in PAIRS:
                ticker = exchange.fetch_ticker(pair)
                price = ticker.get('last', 0.0)
                market_list.append({
                    "pair": pair.split('/')[0],
                    "price": price,
                    "rsi": 48.5,
                    "trend": "NEUTRO"
                })
        except Exception as e:
            logging.error(f"Erro ao ler API da corretora: {e}")

    return jsonify({
        "configured": True,
        "running": bot_state["running"],
        "balance": balance_val,
        "initial_balance": bot_state["initial_balance"] if bot_state["initial_balance"] > 0 else balance_val,
        "active_position": bot_state["active_position"],
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
        is_testnet=False,
        leverage=int(data.get("leverage", 17))
    )
    return jsonify({"status": "success", "message": "Definições guardadas com sucesso."})

def background_trading_loop():
    while True:
        try:
            if bot_state["running"] and are_keys_configured():
                # Lógica do motor de trading
                pass
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
        time.sleep(3)

if __name__ == '__main__':
    t = threading.Thread(target=background_trading_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
