# -*- coding: utf-8 -*-
"""ND-SCALPING — ligação à Bybit (ccxt assíncrono) e tradução dos erros para mensagens claras."""
import re

import ccxt.async_support as ccxt
from ccxt.base import errors as E

MODES = {
    "testnet": "Testnet (testnet.bybit.com)",
    "demo": "Demo Trading (bybit.com, modo demo)",
    "real": "Conta REAL",
}


def mode_label(mode):
    return MODES.get(mode, str(mode))


def create_exchange(state):
    """Cria o cliente Bybit com as definições guardadas no painel."""
    key = str(state.get("api_key", "")).strip()
    secret = str(state.get("api_secret", "")).strip()
    if not key or not secret:
        raise ValueError("Insere a API Key e o API Secret em Ajustes.")

    ex = ccxt.bybit({
        "apiKey": key,
        "secret": secret,
        "enableRateLimit": True,
        "options": {
            "defaultType": "swap",        # futuros perpétuos
            "defaultSubType": "linear",   # contratos USDT
            "adjustForTimeDifference": True,
            "recvWindow": 10000,
        },
    })
    mode = state.get("mode", "testnet")
    if mode == "testnet":
        ex.set_sandbox_mode(True)                      # testnet.bybit.com
    elif mode == "demo":
        if hasattr(ex, "enable_demo_trading"):         # api-demo.bybit.com
            ex.enable_demo_trading(True)
        else:
            ex.urls["api"] = ex.urls["demotrading"]
    return ex


def read_usdt(b):
    """Lê (saldo total, saldo livre) em USDT de um fetch_balance, tanto em conta Unified como Clássica."""
    total = float((b.get("total") or {}).get("USDT") or 0)
    free = float((b.get("free") or {}).get("USDT") or 0)
    try:
        acc = b["info"]["result"]["list"][0]
    except (KeyError, IndexError, TypeError):
        acc = None
    if isinstance(acc, dict):
        if total <= 0:
            total = float(acc.get("totalEquity") or 0)
        if free <= 0:
            free = float(acc.get("totalAvailableBalance") or 0)
    if free <= 0 < total:
        free = total                       # conta sem posições abertas
    return total, free


ZERO_HINT = ("O saldo de trading é 0. Confirma que o USDT está na conta Unified Trading "
             "(na Bybit: Ativos > Transferir, de Funding para Unified Trading).")


async def test_connection(state):
    """Testa a ligação sem iniciar o robô. Devolve (ok, mensagem)."""
    ex = None
    try:
        ex = create_exchange(state)
        await ex.load_markets()                        # público: testa se a Bybit está acessível
        bal = await ex.fetch_balance()                 # privado: testa a chave, o secret e as permissões
        total, free = read_usdt(bal)
        extra = (" " + ZERO_HINT) if total <= 0 else ""
        return True, f"Ligação OK ({mode_label(state.get('mode'))}). Saldo: {total:.4f} USDT (livre {free:.4f}).{extra}"
    except Exception as e:
        return False, explain_error(e, state.get("mode"))[0]
    finally:
        if ex is not None:
            try:
                await ex.close()
            except Exception:
                pass


def explain_error(e, mode="testnet"):
    """Traduz um erro técnico. Devolve (mensagem, fatal).
    fatal=True: o robô para até corrigires o problema. fatal=False: tenta de novo."""
    s = str(e)
    low = s.lower()
    label = mode_label(mode)

    if isinstance(e, ValueError):
        return s, True
    if "10010" in s or "unmatched ip" in low:
        return ("A chave tem restrição de IP. Cria a chave sem restrição de IP "
                "(o IP da Render muda) e cola-a de novo em Ajustes."), True
    if "10004" in s or "error sign" in low or "signature" in low:
        return "API Secret errado (assinatura inválida). Copia o Secret de novo, sem espaços.", True
    if "10005" in s or isinstance(e, E.PermissionDenied) or "permission denied" in low:
        return "A chave não tem permissão. Ativa Leitura + Negociação de Contratos (Contract Trade).", True
    if "10003" in s or "api key is invalid" in low or "invalid api" in low or isinstance(e, E.AuthenticationError):
        return (f"API Key inválida para o modo «{label}». A chave tem de ser criada no mesmo ambiente: "
                "Testnet (testnet.bybit.com), Demo Trading ou conta real. Confirma também a opção em Ajustes."), True
    if "cloudfront" in low or "block access" in low or re.search(r"\b403\b", s) or "forbidden" in low:
        return ("A Bybit bloqueou o IP do servidor (regiões como os EUA são bloqueadas). "
                "Cria o serviço na Render com a Region = Frankfurt."), True
    if "10002" in s or "timestamp" in low or "recv_window" in low:
        return "Relógio fora de sincronia com a Bybit. A tentar de novo.", False
    if "10006" in s or "too many" in low or isinstance(e, E.RateLimitExceeded):
        return "Limite de pedidos da Bybit atingido. A abrandar.", False
    if isinstance(e, E.NetworkError):
        return "Sem ligação à Bybit (rede/timeout). A tentar de novo.", False
    return f"Erro: {s[:110]}", False
