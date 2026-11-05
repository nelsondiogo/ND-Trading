import os

# 6 Pares leves de baixo custo por contrato, ideais para saldos reduzidos
PAIRS = [
    'DOGE/USDT:USDT',
    'XRP/USDT:USDT',
    'ADA/USDT:USDT',
    'PEPE/USDT:USDT',
    'SHIB/USDT:USDT',
    'TRX/USDT:USDT'
]

SCAN_INTERVAL = 2  # Varredura a cada 2 segundos (Alta Frequência)

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
    BYBIT_API_KEY = api_key
    BYBIT_API_SECRET = api_secret
    IS_TESTNET = is_testnet
    LEVERAGE = leverage
    os.environ["BYBIT_API_KEY"] = api_key
    os.environ["BYBIT_API_SECRET"] = api_secret
    os.environ["IS_TESTNET"] = str(is_testnet)
    os.environ["LEVERAGE"] = str(leverage)
