import os
import json

CONFIG_FILE = "settings.json"

PAIRS = [
    'ADA/USDT:USDT',
    'TRX/USDT:USDT',
    'NEAR/USDT:USDT',
    'LTC/USDT:USDT'
]

TAKE_PROFIT_PCT = 0.045  # 4.5% Take Profit Global
STOP_LOSS_PCT = 0.012    # 1.2% Stop Loss Base
TRAILING_ACTIVATION = 0.005 # 0.5% para ativar a trava móvel
LEVERAGE = 17

def load_config():
    settings = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                settings = json.load(f)
        except Exception:
            pass

    api_key = settings.get("api_key", os.environ.get("BYBIT_API_KEY", "")).strip()
    api_secret = settings.get("api_secret", os.environ.get("BYBIT_API_SECRET", "")).strip()
    is_testnet = settings.get("is_testnet", os.environ.get("IS_TESTNET", "False").lower() in ["true", "1"])
    leverage = int(settings.get("leverage", LEVERAGE))

    # Verifica se as chaves são válidas (não vazias e diferentes de placeholders)
    has_keys = bool(api_key and api_secret and "SUA_" not in api_key)

    return {
        "BYBIT_API_KEY": api_key,
        "BYBIT_API_SECRET": api_secret,
        "IS_TESTNET": is_testnet,
        "LEVERAGE": leverage,
        "take_profit": TAKE_PROFIT_PCT,
        "stop_loss": STOP_LOSS_PCT,
        "configured": has_keys
    }

def save_config(api_key, api_secret, is_testnet=False, leverage=17):
    settings = {
        "api_key": api_key.strip(),
        "api_secret": api_secret.strip(),
        "is_testnet": bool(is_testnet),
        "leverage": int(leverage)
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(settings, f)

def are_keys_configured():
    return load_config()["configured"]
