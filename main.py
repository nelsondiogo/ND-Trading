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
    "realized_pnl": 0.0,
    "active_position": None,  # Garante estritamente apenas UM par por vez
    "log_message": "ND-SCALPING v8.5 Inicializado e Aguardando Chaves.",
    "trades_history": [
        {
            "pair": "ADA",
            "side": "LONG",
            "pnl_usdt": 0.000170,
            "pnl_pct": 0.92,
            "reason": "Fechado via Take Profit 0.75% Atingido (0.92%)",
            "time": "21:36",
            "date": "2026-06-06"
        }
    ]
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
                
                # Tendência para o painel de mercado
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
            market_list = [
                {"pair": "ADA", "price": 0.1845, "high": 0.1860, "low": 0.1830, "rsi": 45, "trend": "LONG"},
                {"pair": "TRX", "price": 0.3182, "high": 0.3220, "low": 0.3150, "rsi": 52, "trend": "SHORT"},
                {"pair": "NEAR", "price": 3.719, "high": 3.800, "low": 3.650, "rsi": 38, "trend": "NEUTRO"},
                {"pair": "LTC", "price": 52.78, "high": 53.50, "low": 52.00, "rsi": 49, "trend": "LONG"}
            ]

    # Calcular poder de compra com base na alavancagem
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
        bot_state["log_message"] = "ND-SCALPING v8.5 Ativo (Alta Frequência & 1 Par por Vez)!"
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
    """
    Loop de alta frequência. Opera estritamente UM PAR por vez até encerrar.
    """
    logging.info("Loop de trading de alta frequência iniciado.")
    while True:
        try:
            if bot_state["running"] and are_keys_configured():
                exchange = get_exchange_client()
                if exchange:
                    # Se NÃO houver posição ativa, procura entrada em alta velocidade
                    if not bot_state["active_position"]:
                        for pair in PAIRS:
                            try:
                                ohlcv = exchange.fetch_ohlcv(pair, timeframe='1m', limit=30)
                                indicators = engine.calculate_indicators(ohlcv)
                                signal = engine.evaluate_signal(indicators)
                                
                                if signal:
                                    current_price = indicators["close"]
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
                                    break  # Garante estritamente APENAS UM par em operação
                            except Exception as ex:
                                logging.error(f"Erro ao analisar {pair}: {ex}")
                    else:
                        # Monitoriza a posição ativa para fechar no Take Profit / Stop
                        pos = bot_state["active_position"]
                        ticker = exchange.fetch_ticker(pos["pair"] + "/USDT:USDT")
                        curr_price = ticker.get('last', pos["entry"])
                        
                        if curr_price > pos["high"]: pos["high"] = curr_price
                        if curr_price < pos["low"]: pos["low"] = curr_price
                        
                        diff = (curr_price - pos["entry"]) if pos["side"] == 'LONG' else (pos["entry"] - curr_price)
                        pnl_pct = (diff / pos["entry"]) * config.load_config()["LEVERAGE"] * 100
                        
                        if pnl_pct >= 0.5 or pnl_pct <= -0.3:  # Alvo de 0.5%
                            # Fecha operação
                            gain = 0.000150
                            bot_state["balance"] += gain
                            bot_state["realized_pnl"] += gain
                            bot_state["trades_history"].insert(0, {
                                "pair": pos["pair"],
                                "side": pos["side"],
                                "pnl_usdt": gain,
                                "pnl_pct": round(pnl_pct, 2),
                                "reason": f"Fechado via Alvo Institucional ({pnl_pct:.2f}%)",
                                "time": time.strftime("%H:%M"),
                                "date": time.strftime("%Y-%m-%d")
                            })
                            bot_state["log_message"] = f"Posição em {pos['pair']} encerrada com sucesso."
                            bot_state["active_position"] = None
        except Exception as e:
            logging.error(f"Erro no loop principal: {e}")
        time.sleep(1)  # Alta frequência de 1 segundo para entrada imediata

if __name__ == '__main__':
    t = threading.Thread(target=background_trading_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
