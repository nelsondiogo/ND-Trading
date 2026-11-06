import os

PAIRS = [
    'ADA/USDT:USDT',
    'TRX/USDT:USDT',
    'NEAR/USDT:USDT',
    'LTC/USDT:USDT'
]

SCAN_INTERVAL = 1  # Alta frequência para máxima velocidade de entrada

_config_store = {
    "BYBIT_API_KEY": os.environ.get("BYBIT_API_KEY", ""),
    "BYBIT_API_SECRET": os.environ.get("BYBIT_API_SECRET", ""),
    "IS_TESTNET": os.environ.get("IS_TESTNET", "False").lower() in ["true", "1"],
    "LEVERAGE": int(os.environ.get("LEVERAGE", 17))
}

def are_keys_configured():
    return bool(_config_store["BYBIT_API_KEY"].strip() and _config_store["BYBIT_API_SECRET"].strip())

def load_config():
    return {
        "BYBIT_API_KEY": _config_store["BYBIT_API_KEY"],
        "BYBIT_API_SECRET": _config_store["BYBIT_API_SECRET"],
        "IS_TESTNET": _config_store["IS_TESTNET"],
        "LEVERAGE": _config_store["LEVERAGE"],
        "configured": are_keys_configured()
    }

def save_config(api_key, api_secret, is_testnet, leverage):
    _config_store["BYBIT_API_KEY"] = api_key.strip()
    _config_store["BYBIT_API_SECRET"] = api_secret.strip()
    _config_store["IS_TESTNET"] = bool(is_testnet)
    _config_store["LEVERAGE"] = int(leverage)
    os.environ["BYBIT_API_KEY"] = _config_store["BYBIT_API_KEY"]
    os.environ["BYBIT_API_SECRET"] = _config_store["BYBIT_API_SECRET"]
