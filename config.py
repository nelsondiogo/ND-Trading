import os
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# CONFIGURAÇÃO DIRETA DE API E CREDENCIAIS
# ==========================================
# Podes inserir as tuas chaves da Bybit diretamente aqui entre as aspas,
# ou manter o os.getenv para puxar do Render/ambiente de forma segura.
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "AQUI_A_TUA_API_KEY_DA_BYBIT")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "AQUI_O_TEU_API_SECRET_DA_BYBIT")

# Altera para "false" se fores usar conta real (Mainnet), ou "true" para testes (Testnet)
IS_TESTNET = os.getenv("IS_TESTNET", "true").lower() == "true"

# Pares de moedas monitorizados em simultâneo
PAIRS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "BNB/USDT:USDT"
]

# Configurações de Gestão de Risco e Estratégia
SCAN_INTERVAL = 18                  # Intervalo de scan (15 a 20 segundos)
ADX_THRESHOLD = 25.0                # Força mínima de tendência
TRAILING_ACTIVATION_THRESHOLD = 0.01  # Ativa o trailing stop ao atingir +1%
TRAILING_DRAWDOWN_PERCENT = 0.30      # Fecha se o lucro recuar 30% do pico máximo
