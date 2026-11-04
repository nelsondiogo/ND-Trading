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

_current_config = load_config()

BYBIT_API_KEY = _current_config["BYBIT_API_KEY"]
BYBIT_API_SECRET = _current_config["BYBIT_API_SECRET"]
IS_TESTNET = _current_config["IS_TESTNET"]

# Pares atualizados com ativos de menor valor nominal (DOGE, XRP, ADA, BTC) para ordens menores
PAIRS = [
    "DOGE/USDT:USDT",
    "XRP/USDT:USDT",
    "ADA/USDT:USDT",
    "BTC/USDT:USDT"
]

SCAN_INTERVAL = 15
ADX_THRESHOLD = 20.0
TRAILING_ACTIVATION_THRESHOLD = 0.008
TRAILING_DRAWDOWN_PERCENT = 0.25
