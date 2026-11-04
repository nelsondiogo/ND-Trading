import os

PAIRS = [
    'DOGE/USDT:USDT',
    'XRP/USDT:USDT',
    'ADA/USDT:USDT',
    'SOL/USDT:USDT',
    'LINK/USDT:USDT',
    'AVAX/USDT:USDT',
    'NEAR/USDT:USDT',
    'PEPE/USDT:USDT',
    'SHIB/USDT:USDT',
    'RENDER/USDT:USDT'
]

SCAN_INTERVAL = 2
USER_LEVERAGE = 10 

# Atributos diretos para compatibilidade total com o main.py
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "cIHTUlByBnrfkEy8S")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
IS_TESTNET = True

def load_config():
    return {
        "BYBIT_API_KEY": BYBIT_API_KEY,
        "BYBIT_API_SECRET": BYBIT_API_SECRET,
        "IS_TESTNET": IS_TESTNET,
        "LEVERAGE": int(os.getenv("USER_LEVERAGE", USER_LEVERAGE))
    }

def save_config(api_key, api_secret, is_testnet, leverage=10):
    global BYBIT_API_KEY, BYBIT_API_SECRET, IS_TESTNET, USER_LEVERAGE
    BYBIT_API_KEY = api_key
    BYBIT_API_SECRET = api_secret
    IS_TESTNET = is_testnet
    USER_LEVERAGE = int(leverage)
    os.environ["BYBIT_API_KEY"] = api_key
    os.environ["BYBIT_API_SECRET"] = api_secret
