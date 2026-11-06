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
    "active_position": None
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
    cfg = load_config()
    if not are_keys_configured():
        return jsonify({
            "configured": False,
            "running": False,
            "balance": 0.0,
            "initial_balance": 0.0,
            "market": [],
            "active_position": None,
            "config": cfg,
            "message": "Aguardando chaves API."
        })

    exchange = get_exchange_client()
    balance_val = 0.2548
    market_list = []

    if exchange:
        try:
            bal = exchange.fetch_balance()
            total_bal = float(bal.get('total', {}).get('USDT', 0.0))
            if total_bal > 0:
                balance_val = total_bal

            for pair in PAIRS:
                ticker = exchange.fetch_ticker(pair)
                price = ticker.get('last', 0.0)
                high = ticker.get('high', price)
                low = ticker.get('low', price)
                market_list.append({
                    "pair": pair.split('/')[0],
                    "price": price,
                    "high": high,
                    "low": low,
                    "rsi": 50.0,
                    "trend": "SUBIDA" if price >= low else "DESCIDA"
                })
        except Exception as e:
            logging.error(f"Erro ao ler API Bybit: {e}")
            # Fallback seguro para teste visual se a rede falhar momentaneamente
            market_list = [
                {"pair": "ADA", "price": 0.1845, "high": 0.1860, "low": 0.1830, "rsi": 45, "trend": "NEUTRO"},
                {"pair": "TRX", "price": 0.3182, "high": 0.3220, "low": 0.3150, "rsi": 52, "trend": "SUBIDA"},
                {"pair": "NEAR", "price": 3.719, "high": 3.800, "low": 3.650, "rsi": 38, "trend": "DESCIDA"},
                {"pair": "LTC", "price": 52.78, "high": 53.50, "low": 52.00, "rsi": 49, "trend": "NEUTRO"}
            ]

    return jsonify({
        "configured": True,
        "running": bot_state["running"],
        "balance": balance_val,
        "initial_balance": bot_state["initial_balance"] if bot_state["initial_balance"] > 0 else balance_val,
        "active_position": bot_state["active_position"],
        "market": market_list,
        "config": cfg,
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
                pass
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
        time.sleep(3)

if __name__ == '__main__':
    t = threading.Thread(target=background_trading_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
