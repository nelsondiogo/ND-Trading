import time
import threading
import logging
from flask import Flask, render_template, request, jsonify
from config import load_config, save_config, PAIRS
from trading_engine import TradingEngine

# Configuração de Logs Institucionais
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

app = Flask(__name__)
config = load_config()
engine = TradingEngine(config)

# Estado global do robô
bot_state = {
    "running": True,
    "balance": 0.330964,
    "initial_balance": 0.330964,
    "active_position": None,
    "trades_history": [],
    "market_data": {}
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    return jsonify({
        "running": bot_state["running"],
        "balance": bot_state["balance"],
        "initial_balance": bot_state["initial_balance"],
        "active_position": bot_state["active_position"],
        "pairs": PAIRS
    })

@app.route('/api/history')
def history():
    return jsonify(bot_state["trades_history"])

@app.route('/api/toggle', methods=['POST'])
def toggle_bot():
    bot_state["running"] = not bot_state["running"]
    state_msg = "ativado" if bot_state["running"] else "parado"
    logging.info(f"Estado do motor alterado: {state_msg}")
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
    return jsonify({"status": "success", "message": "Configurações atualizadas com sucesso."})

def background_trading_loop():
    """
    Loop de execução em segundo plano para varredura de alta frequência
    e monitorização dos 4 pares de elite.
    """
    logging.info("Loop de background trading iniciado com rigor institucional.")
    while True:
        try:
            if bot_state["running"]:
                # Simulação de varredura e atualização de mercado para os 4 pares
                for pair in PAIRS:
                    # Aqui o motor analisa indicadores e gere posições ativas
                    pass
        except Exception as e:
            logging.error(f"Erro no loop principal de trading: {e}")
        time.sleep(2)

if __name__ == '__main__':
    # Inicia a thread de background para o robô
    t = threading.Thread(target=background_trading_loop, daemon=True)
    t.start()
    
    # Inicia o servidor web Flask
    app.run(host='0.0.0.0', port=5000, debug=False)
