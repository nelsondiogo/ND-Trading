import os
import json

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "BYBIT_API_KEY": "",
        "BYBIT_API_SECRET": "",
        "IS_TESTNET": False
    }

def save_config(api_key, api_secret, is_testnet):
    config_data = {
        "BYBIT_API_KEY": api_key,
        "BYBIT_API_SECRET": api_secret,
        "IS_TESTNET": is_testnet
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f, indent=4)

# Carrega definições iniciais
_current_config = load_config()

BYBIT_API_KEY = _current_config["BYBIT_API_KEY"]
BYBIT_API_SECRET = _current_config["BYBIT_API_SECRET"]
IS_TESTNET = _current_config["IS_TESTNET"]

# Pares e parâmetros fixos de trading
PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT"]
SCAN_INTERVAL = 18
ADX_THRESHOLD = 25.0
TRAILING_ACTIVATION_THRESHOLD = 0.01
TRAILING_DRAWDOWN_PERCENT = 0.30
