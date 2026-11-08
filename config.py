# -*- coding: utf-8 -*-
"""
ND-SCALPING — configuração fixa.

Qualquer valor pode ser sobreposto por uma variável de ambiente na Render
(Environment) sem mexer no código. A chave da API NÃO fica aqui: é inserida no
separador "Ajustes" do painel (ou em BYBIT_API_KEY / BYBIT_API_SECRET na Render).
"""
import os


def _env(name, default):
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return type(default)(v)


# ============================ PARES (moedas abaixo de 1 USDT) ============================
# O bot só opera esta lista. A cada varredura confirma ao vivo que o preço está abaixo de
# MAX_PRICE_USDT: se uma moeda subir acima de 1 USDT, sai sozinha da rotação.
# Pares que não existam no ambiente da Bybit são ignorados (aparece no log ao ligar).
MAX_PRICE_USDT = _env("MAX_PRICE_USDT", 1.0)
PAIR_BASES = [
    "DOGE", "ADA", "TRX", "XLM", "HBAR", "VET", "ALGO", "SAND", "MANA", "GALA",
    "CHZ", "IOTA", "SEI", "ARB", "POL", "JASMY", "ONDO", "CRV", "SUSHI", "APE",
    "1INCH", "CFX", "ENA", "W", "STRK", "PYTH", "JUP", "DYDX", "LDO", "KAS",
    "1000PEPE", "1000BONK", "1000FLOKI", "SHIB1000", "1000SATS", "1000XEC",
    "1000LUNC", "WIF", "PENGU", "FARTCOIN", "TURBO", "MEME", "NOT", "DOGS",
    "HMSTR", "PNUT", "POPCAT", "MOODENG", "GOAT", "BOME", "MEW", "ACT",
    "1000NEIROCTO", "GRASS",
]
PAIRS = [f"{b}/USDT:USDT" for b in PAIR_BASES]

# ============================ PADRÕES DAS DEFINIÇÕES ============================
# Editáveis depois no separador "Ajustes" do painel.
LEVERAGE_DEFAULT = _env("LEVERAGE", 17)                  # alavancagem
MARGIN_DEFAULT_USDT = _env("MARGIN_PER_TRADE_USDT", 20.0)  # margem por operação (USDT)
MODE_DEFAULT = os.getenv("BYBIT_MODE", "testnet")        # testnet | demo | real
MARGIN_MODE = "cross"                                    # margem cruzada
ALLOW_LONG = _env("ALLOW_LONG", 1) == 1
ALLOW_SHORT = _env("ALLOW_SHORT", 1) == 1

# ============================ FILTRO PRÉ-ENTRADA ============================
MAX_1M_MOVE_PCT = _env("MAX_1M_MOVE_PCT", 1.5)           # rejeita amplitude > 1,5% numa vela de 1 min
MIN_VOL_RATIO = _env("MIN_VOL_RATIO", 1.5)               # volume da vela vs média das 20 anteriores
MIN_QUOTE_VOLUME_24H = _env("MIN_VOL", 10000000.0)       # volume 24h mínimo (USDT); ignorado na testnet
MAX_SPREAD_PCT = _env("MAX_SPREAD_PCT", 0.08)            # spread bid/ask máximo; ignorado na testnet
MAX_TICK_PCT = _env("MAX_TICK_PCT", 0.05)                # tick do preço, em % do preço
TOP_N = _env("TOP_N", 25)                                # pares analisados por varredura
SCAN_INTERVAL_S = _env("SCAN_INTERVAL_S", 2.0)

# ============================ MATRIZ DE RISCO (LONG; no SHORT é o espelho) ============================
SL_PCT = _env("SL_PCT", 0.25)                            # stop loss inicial: 0,25% contra a entrada
TP_PCT = _env("TP_PCT", 0.95)                            # take profit inicial: 0,95% a favor
TRAIL_TRIGGER_PCT = _env("TRAIL_TRIGGER_PCT", 0.45)      # lucro que ativa o stop rígido "Dinamite"
TRAIL_DISTANCE_PCT = _env("TRAIL_DISTANCE_PCT", 0.0)     # 0 = stop rígido exatamente no cume
REVERSAL_DROP_PCT = _env("REVERSAL_DROP_PCT", 0.18)      # inversão brusca ANTES da Dinamite => fecha
REVERSAL_WINDOW_S = _env("REVERSAL_WINDOW_S", 6)

# ============================ CONTROLO ============================
POLL_INTERVAL_S = _env("POLL_INTERVAL_S", 0.5)           # leitura de preço com posição aberta
COOLDOWN_S = _env("COOLDOWN_S", 45)                      # pausa no par após ganho
COOLDOWN_LOSS_S = _env("COOLDOWN_LOSS_S", 300)           # pausa no par após perda
MAX_CONSEC_LOSSES = _env("MAX_CONSEC_LOSSES", 4)         # perdas seguidas => pausa geral
PAUSE_AFTER_LOSSES_S = _env("PAUSE_AFTER_LOSSES_S", 900)
MAX_DAILY_LOSS_USDT = _env("MAX_DAILY_LOSS_USDT", 30.0)  # para o robô ao atingir esta perda no dia
TZ_OFFSET_H = _env("TZ_OFFSET_H", 1)                     # fuso do painel (Angola = UTC+1)
