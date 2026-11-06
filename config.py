import os

PAIRS = [
    'ADA/USDT:USDT',
    'TRX/USDT:USDT',
    'NEAR/USDT:USDT',
    'LTC/USDT:USDT'
]

SCAN_INTERVAL = 2

BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
IS_TESTNET = os.environ.get("IS_TESTNET", "False").lower() in ["true", "1"]
LEVERAGE = int(os.environ.get("LEVERAGE", 17))

def load_config():
    return {
        "BYBIT_API_KEY": BYBIT_API_KEY,
        "BYBIT_API_SECRET": BYBIT_API_SECRET,
        "IS_TESTNET": IS_TESTNET,
        "LEVERAGE": LEVERAGE
    }

def save_config(api_key, api_secret, is_testnet, leverage):
    global BYBIT_API_KEY, BYBIT_API_SECRET, IS_TESTNET, LEVERAGE
    BYBIT_API_KEY = api_key.strip()
    BYBIT_API_SECRET = api_secret.strip()
    IS_TESTNET = is_testnet
    LEVERAGE = int(leverage)
    os.environ["BYBIT_API_KEY"] = BYBIT_API_KEY
    os.environ["BYBIT_API_SECRET"] = BYBIT_API_SECRET
