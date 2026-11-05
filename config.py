import os

# Credenciais e Definições da Bybit
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "cIHTUlByBnrfkEy8S")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "tua_api_secret_aqui")
IS_TESTNET = False  # Definido para False para operar na conta real

# Fase Inicial: Apenas os 3 pares de alta liquidez abaixo de 1 USDT
PAIRS = [
    'DOGE/USDT:USDT',
    'XRP/USDT:USDT',
    'ADA/USDT:USDT'
]

SCAN_INTERVAL = 3  # Intervalo em segundos entre as varreduras do bot

def load_config():
    """Carrega as definições atuais para o painel de ajustes"""
    return {
        "BYBIT_API_KEY": BYBIT_API_KEY,
        "BYBIT_API_SECRET": BYBIT_API_SECRET,
        "IS_TESTNET": IS_TESTNET,
        "LEVERAGE": 17  # Alavancagem manual predefinida
    }

def save_config(api_key, api_secret, is_testnet, leverage):
    """Guarda novas definições (atualiza em memória/ambiente)"""
    global BYBIT_API_KEY, BYBIT_API_SECRET, IS_TESTNET
    BYBIT_API_KEY = api_key
    BYBIT_API_SECRET = api_secret
    IS_TESTNET = is_testnet
