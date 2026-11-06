import time
import threading
import logging
import ccxt
from flask import Flask, request, jsonify
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
    "realized_pnl": 0.0,
    "active_position": None,
    "log_message": "ND-SCALPING v8.5 Operacional.",
    "trades_history": []
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
    return jsonify({
        "bot": "ND-SCALPING v8.5",
        "status": "Online",
        "running": bot_state["running"],
        "configured": are_keys_configured(),
        "endpoints": {
            "status": "/api/status",
            "toggle": "/api/toggle (POST)",
            "settings": "/api/settings (POST com api_key e api_secret)"
        }
    })

@app.route('/api/status')
def status():
    cfg = load_config()
    if not are_keys_configured():
        return jsonify({
            "configured": False,
            "running": False,
            "balance": 0.0,
            "market": [],
            "active_position": None,
            "log": "Aguardando inserção de chaves em /api/settings."
        })

    exchange = get_exchange_client()
    balance_val = bot_state["balance"]
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
                    "trend": "LONG" if price > low else "SHORT"
                })
        except Exception as e:
            logging.error(f"Erro Bybit API: {e}")

    return jsonify({
        "configured": True,
        "running": bot_state["running"],
        "balance": balance_val,
        "realized_pnl": bot_state["realized_pnl"],
        "active_position": bot_state["active_position"],
        "market": market_list,
        "history": bot_state["trades_history"],
        "log": bot_state["log_message"]
    })

@app.route('/api/toggle', methods=['POST'])
def toggle_bot():
    if not are_keys_configured():
        return jsonify({"error": "Configure as chaves API primeiro através de /api/settings."}), 400
    bot_state["running"] = not bot_state["running"]
    bot_state["log_message"] = "ND-SCALPING Ativo." if bot_state["running"] else "Robô parado."
    return jsonify({"running": bot_state["running"], "log": bot_state["log_message"]})

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Recebe as chaves API enviadas pelo utilizador"""
    data = request.json or request.form
    api_key = data.get("api_key", "")
    api_secret = data.get("api_secret", "")
    is_testnet = data.get("is_testnet", False)
    leverage = int(data.get("leverage", 17))

    if not api_key or not api_secret:
        return jsonify({"status": "error", "message": "API Key e API Secret são obrigatórias."}), 400

    save_config(api_key, api_secret, is_testnet, leverage)
    bot_state["log_message"] = "Chaves API configuradas com sucesso!"
    
    return jsonify({
        "status": "success",
        "message": "Chaves da Bybit guardadas com sucesso. O robô já está pronto para arrancar.",
        "configured": are_keys_configured()
    })

def background_trading_loop():
    while True:
        try:
            if bot_state["running"] and are_keys_configured():
                exchange = get_exchange_client()
                if exchange and not bot_state["active_position"]:
                    for pair in PAIRS:
                        ohlcv = exchange.fetch_ohlcv(pair, timeframe='1m', limit=30)
                        indicators = engine.calculate_indicators(ohlcv)
                        signal = engine.evaluate_signal(indicators)
                        if signal:
                            current_price = indicators["close"]
                            engine.peak_price = current_price
                            engine.active_stop_price = 0.0
                            bot_state["active_position"] = {
                                "pair": pair.split('/')[0],
                                "side": signal,
                                "entry": current_price
                            }
                            bot_state["log_message"] = f"Posição aberta em {pair.split('/')[0]} ({signal})."
                            break
        except Exception as e:
            logging.error(f"Erro no loop de trading: {e}")
        time.sleep(1)

if __name__ == '__main__':
    t = threading.Thread(target=background_trading_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
