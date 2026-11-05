import os

# Variáveis globais para as credenciais (vazias por defeito para inserção limpa)
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
IS_TESTNET = False

PAIRS = [
    'DOGE/USDT:USDT',
    'XRP/USDT:USDT',
    'ADA/USDT:USDT'
]

SCAN_INTERVAL = 3

def load_config():
    return {
        "BYBIT_API_KEY": BYBIT_API_KEY,
        "BYBIT_API_SECRET": BYBIT_API_SECRET,
        "IS_TESTNET": IS_TESTNET,
        "LEVERAGE": 17
    }

def save_config(api_key, api_secret, is_testnet, leverage):
    global BYBIT_API_KEY, BYBIT_API_SECRET, IS_TESTNET
    BYBIT_API_KEY = api_key.strip()
    BYBIT_API_SECRET = api_secret.strip()
    IS_TESTNET = is_testnet
