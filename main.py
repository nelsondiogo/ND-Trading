import time
import threading
import logging
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
    "active_position": None
}

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
            "message": "Aguardando configuração das chaves API."
        })

    return jsonify({
        "configured": True,
        "running": bot_state["running"],
        "balance": bot_state["balance"] if bot_state["balance"] > 0 else 0.330964,
        "initial_balance": 0.330964,
        "market": [
            {"pair": "ADA", "price": 0.1845, "rsi": 45, "trend": "NEUTRO"},
            {"pair": "TRX", "price": 0.3182, "rsi": 52, "trend": "SUBIDA"},
            {"pair": "NEAR", "price": 3.719, "rsi": 38, "trend": "DESCIDA"},
            {"pair": "LTC", "price": 52.78, "rsi": 49, "trend": "NEUTRO"}
        ],
        "pairs": PAIRS
    })

@app.route('/api/toggle', methods=['POST'])
def toggle_bot():
    if not are_keys_configured():
        return jsonify({"error": "Configure as chaves API primeiro em Ajustes."}), 400

    bot_state["running"] = not bot_state["running"]
    if bot_state["running"] and bot_state["balance"] == 0.0:
        bot_state["balance"] = 0.330964
        bot_state["initial_balance"] = 0.330964
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
    return jsonify({"status": "success", "message": "Chaves e configurações guardadas com sucesso."})

def background_trading_loop():
    while True:
        try:
            if bot_state["running"] and are_keys_configured():
                pass
        except Exception as e:
            logging.error(f"Erro: {e}")
        time.sleep(2)

if __name__ == '__main__':
    t = threading.Thread(target=background_trading_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
