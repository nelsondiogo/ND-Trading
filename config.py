# -*- coding: utf-8 -*-
"""
ND-SCALPING — configuração fixa.

Valores técnicos (não são segredos) podem ser sobrepostos por variáveis de ambiente, mas
nenhuma é necessária. A palavra-passe do painel e as chaves da Bybit NÃO ficam aqui nem na
Render: são inseridas no próprio painel (1.º acesso e separador "Ajustes").
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
MARGIN_DEFAULT_USDT = _env("MARGIN_PER_TRADE_USDT", 5.0)   # margem por operação (USDT): posição = margem x alavancagem
MODE_DEFAULT = "testnet"                                # testnet | demo | real (muda em Ajustes)
MARGIN_MODE = "cross"                                    # margem cruzada
ALLOW_LONG = _env("ALLOW_LONG", 1) == 1
ALLOW_SHORT = _env("ALLOW_SHORT", 1) == 1

# ============================ FILTRO PRÉ-ENTRADA ============================
MAX_1M_MOVE_PCT = _env("MAX_1M_MOVE_PCT", 1.5)           # rejeita amplitude > 1,5% numa vela de 1 min
MIN_VOL_RATIO = _env("MIN_VOL_RATIO", 0.7)               # confirmação: volume da vela vs mediana das 20 anteriores
MIN_QUOTE_VOLUME_24H = _env("MIN_VOL", 10000000.0)       # volume 24h mínimo (USDT); ignorado na testnet
MAX_SPREAD_PCT = _env("MAX_SPREAD_PCT", 0.08)            # spread bid/ask máximo; ignorado na testnet
MAX_TICK_PCT = _env("MAX_TICK_PCT", 0.10)                # tick do preço, em % do preço
TOP_N = _env("TOP_N", 60)                                # pares analisados por varredura (todos os elegíveis)
TICKER_INTERVAL_S = _env("TICKER_INTERVAL_S", 1.0)       # preços ao vivo no painel (1 pedido por segundo)
SCAN_INTERVAL_S = _env("SCAN_INTERVAL_S", 3.0)           # velas de 1 min e sinais
SCAN_BUSY_S = _env("SCAN_BUSY_S", 10.0)                  # varredura mais lenta com posição aberta (prioriza o stop)

# ============================ MATRIZ DE RISCO (LONG; no SHORT é o espelho) ============================
SL_PCT = _env("SL_PCT", 0.50)                            # stop loss inicial: 0,50% contra a entrada (aguenta o ruído do mercado)
TP_PCT = _env("TP_PCT", 0.95)                            # take profit inicial: 0,95% a favor
TRAIL_TRIGGER_PCT = _env("TRAIL_TRIGGER_PCT", 0.12)      # a este lucro a favor, o stop trava rígido no cume (nenhum recuo)
TRAIL_DISTANCE_PCT = _env("TRAIL_DISTANCE_PCT", 0.0)     # 0 = stop rígido exatamente no cume
REVERSAL_DROP_PCT = _env("REVERSAL_DROP_PCT", 0.35)      # choque brusco contra a posição ANTES da trava => fecha
REVERSAL_WINDOW_S = _env("REVERSAL_WINDOW_S", 8)

# ============================ CONTROLO ============================
POLL_INTERVAL_S = _env("POLL_INTERVAL_S", 0.3)           # leitura de preço com posição aberta
COOLDOWN_S = _env("COOLDOWN_S", 45)                      # pausa no par após ganho
COOLDOWN_LOSS_S = _env("COOLDOWN_LOSS_S", 300)           # pausa no par após perda
MAX_CONSEC_LOSSES = _env("MAX_CONSEC_LOSSES", 4)         # perdas seguidas => pausa geral
PAUSE_AFTER_LOSSES_S = _env("PAUSE_AFTER_LOSSES_S", 900)
MAX_DAILY_LOSS_PCT = _env("MAX_DAILY_LOSS_PCT", 20.0)    # para as entradas ao perder esta % do saldo no dia
TZ_OFFSET_H = _env("TZ_OFFSET_H", 1)                     # fuso do painel (Angola = UTC+1)

# ============================ SALDO PEQUENO ============================
BALANCE_USE_PCT = _env("BALANCE_USE_PCT", 96.0)          # máx. % do saldo livre usada (margem + taxas); o resto é folga
FEE_RESERVE_PCT = _env("FEE_RESERVE_PCT", 0.12)          # % da posição reservada para as taxas de abrir e fechar
MIN_NOTIONAL_FALLBACK = _env("MIN_NOTIONAL_FALLBACK", 5.0)  # ordem mínima da Bybit (USDT) se o contrato não indicar

# ============================ PAINEL ============================
CHART_POINTS = _env("CHART_POINTS", 600)                 # pontos do gráfico da ordem aberta (0,5 s cada)
HISTORY_MAX = _env("HISTORY_MAX", 500)                   # operações guardadas no histórico

# ============================ QUALIDADE DAS ENTRADAS ============================
# O robô só entra com tendência clara (EMA 9 > 21 > 50 no mesmo sentido), volatilidade suficiente para pagar as
# taxas, preço não esticado e um número mínimo de confirmações (rigor 1 a 5; editável em Ajustes).
ENTRY_RIGOR = _env("ENTRY_RIGOR", 3)                     # 1 = só tendência | 3 = equilibrado | 5 = todas as confirmações
CANDLES_LIMIT = _env("CANDLES_LIMIT", 70)                # velas de 1 min analisadas por par (cerca de 1 hora)
MIN_ATR_PCT = _env("MIN_ATR_PCT", 0.15)                  # volatilidade mínima (ATR de 1 min, em %) para pagar as taxas
MAX_ATR_PCT = _env("MAX_ATR_PCT", 1.2)                   # acima disto o mercado está desordenado demais
EXTENDED_ATR_MULT = _env("EXTENDED_ATR_MULT", 2.5)       # não persegue: distância à EMA21 máxima = 2,5 x ATR
MIN_BODY_RATIO = _env("MIN_BODY_RATIO", 0.35)            # corpo mínimo da última vela, em % da sua amplitude
BTC_BLOCK_PCT = _env("BTC_BLOCK_PCT", 0.15)              # não entra contra um movimento do BTC maior que isto (5 min)
PAIR_LOSS_PAUSE_S = _env("PAIR_LOSS_PAUSE_S", 1800)      # pausa no par após 2 perdas seguidas nele
