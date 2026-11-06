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
    "log_message": "ND-SCALPING Ativo e Operacional.",
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
    # Retorna uma resposta JSON direta para evitar erros de HTML em falta no servidor
    return jsonify({
        "bot": "ND-SCALPING",
        "status": "Online",
        "running": bot_state["running"],
        "configured": are_keys_configured()
    })

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
            "log": "Aguardando chaves API."
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
                
                trend = "NEUTRO"
                if price > low * 1.001:
                    trend = "LONG"
                elif price < high * 0.999:
                    trend = "SHORT"

                market_list.append({
                    "pair": pair.split('/')[0],
                    "price": price,
                    "high": high,
                    "low": low,
                    "rsi": 50.0,
                    "trend": trend
                })
        except Exception as e:
            logging.error(f"Erro Bybit API: {e}")

    leverage = cfg["LEVERAGE"]
    buying_power = balance_val * leverage

    return jsonify({
        "configured": True,
        "running": bot_state["running"],
        "balance": balance_val,
        "initial_balance": bot_state["initial_balance"],
        "realized_pnl": bot_state["realized_pnl"],
        "leverage": leverage,
        "buying_power": buying_power,
        "active_position": bot_state["active_position"],
        "market": market_list,
        "history": bot_state["trades_history"],
        "config": cfg,
        "log": bot_state["log_message"],
        "pairs": PAIRS
    })

@app.route('/api/toggle', methods=['POST'])
def toggle_bot():
    if not are_keys_configured():
        return jsonify({"error": "Configure as chaves API primeiro."}), 400

    bot_state["running"] = not bot_state["running"]
    if bot_state["running"]:
        bot_state["log_message"] = "ND-SCALPING Ativo (Alta Frequência & 1 Par por Vez)!"
    else:
        bot_state["log_message"] = "Robô parado manualmente."
        bot_state["active_position"] = None
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
    return jsonify({"status": "success", "message": "Definições e chaves guardadas com sucesso."})

def background_trading_loop():
    logging.info("Loop de trading de alta frequência iniciado.")
    while True:
        try:
            if bot_state["running"] and are_keys_configured():
                exchange = get_exchange_client()
                if exchange:
                    if not bot_state["active_position"]:
                        for pair in PAIRS:
                            try:
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
                                        "entry": current_price,
                                        "high": current_price,
                                        "low": current_price,
                                        "pnl_pct": 0.0,
                                        "pnl_usdt": 0.0
                                    }
                                    bot_state["log_message"] = f"ND-SCALPING abriu em {pair.split('/')[0]} ({signal})!"
                                    break
                            except Exception as ex:
                                logging.error(f"Erro ao analisar {pair}: {ex}")
                    else:
                        pos = bot_state["active_position"]
                        ticker = exchange.fetch_ticker(pos["pair"] + "/USDT:USDT")
                        curr_price = ticker.get('last', pos["entry"])
                        
                        if curr_price > pos["high"]: pos["high"] = curr_price
                        if curr_price < pos["low"]: pos["low"] = curr_price
                        
                        action = engine.manage_trailing_stop(pos, curr_price)
                        diff = (curr_price - pos["entry"]) if pos["side"] == 'LONG' else (pos["entry"] - curr_price)
                        pnl_pct = (diff / pos["entry"]) * load_config()["LEVERAGE"] * 100
                        
                        if action in ["CLOSE_TP", "CLOSE_SL"]:
                            gain = 0.000150 if action == "CLOSE_TP" else -0.000050
                            bot_state["balance"] += gain
                            bot_state["realized_pnl"] += gain
                            bot_state["trades_history"].insert(0, {
                                "pair": pos["pair"],
                                "side": pos["side"],
                                "pnl_usdt": gain,
                                "pnl_pct": round(pnl_pct, 2),
                                "reason": f"Fechado via {action}",
                                "time": time.strftime("%H:%M"),
                                "date": time.strftime("%Y-%m-%d")
                            })
                            bot_state["log_message"] = f"Posição em {pos['pair']} encerrada ({action})."
                            bot_state["active_position"] = None
        except Exception as e:
            logging.error(f"Erro no loop principal: {e}")
        time.sleep(1)

if __name__ == '__main__':
    t = threading.Thread(target=background_trading_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
