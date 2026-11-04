import os

# Lista dinâmica de 10 pares de alta liquidez para scalping
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

SCAN_INTERVAL = 2  # Alta frequência (varredura a cada 2 segundos)

# Alavancagem manual configurável (pode ser ajustada pelo utilizador)
USER_LEVERAGE = 10 

def load_config():
    return {
        "BYBIT_API_KEY": os.getenv("BYBIT_API_KEY", "cIHTUlByBnrfkEy8S"),
        "BYBIT_API_SECRET": os.getenv("BYBIT_API_SECRET", ""),
        "IS_TESTNET": True,
        "LEVERAGE": int(os.getenv("USER_LEVERAGE", USER_LEVERAGE))
    }

def save_config(api_key, api_secret, is_testnet, leverage=10):
    os.environ["BYBIT_API_KEY"] = api_key
    os.environ["BYBIT_API_SECRET"] = api_secret
    global USER_LEVERAGE
    USER_LEVERAGE = int(leverage)
