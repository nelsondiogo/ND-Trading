# -*- coding: utf-8 -*-
"""ND-SCALPING — ligação à Bybit (ccxt assíncrono) e tradução dos erros para mensagens claras."""
import asyncio
import re
import socket
import time

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
        "timeout": 15000,                 # 15 s por pedido: nunca fica pendurado
    })
    # Não pede a lista de moedas (pedido privado extra que falha com chaves sem permissão de carteira
    # e na conta Demo): para operar só são precisos os contratos e o saldo.
    ex.has = dict(ex.has)
    ex.has["fetchCurrencies"] = False
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


HOSTS = {"real": "api.bybit.com", "demo": "api-demo.bybit.com", "testnet": "api-testnet.bybit.com"}


async def _dns(host):
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM), 8)
    return infos[0][4][0]


async def _http_get(url, timeout=10):
    import aiohttp
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
        async with s.get(url) as r:
            return r.status, (await r.text())[:300]


async def diagnose(state):
    """Testa a ligação passo a passo, sem iniciar o robô. Devolve (ok, [linhas])."""
    steps = []

    def add(ok, text):
        steps.append(("✔ " if ok else "✖ ") + text)

    mode = state.get("mode", "testnet")
    host = HOSTS.get(mode, "api.bybit.com")
    add_ms = lambda t0: int((time.time() - t0) * 1000)

    t0 = time.time()
    try:
        add(True, f"DNS {host} → {await _dns(host)} ({add_ms(t0)} ms)")
    except Exception as e:
        add(False, f"DNS de {host} falhou ({type(e).__name__}): o servidor não resolve o endereço da Bybit.")
        return False, steps

    try:
        _, body = await _http_get("https://api.ipify.org", 6)
        steps.append(f"• IP de saída do servidor: {body.strip()}")
    except Exception:
        steps.append("• IP de saída do servidor: indisponível")

    t0 = time.time()
    try:
        status, body = await _http_get(f"https://{host}/v5/market/time", 10)
    except Exception as e:
        add(False, f"Sem resposta de {host} ({type(e).__name__}, {add_ms(t0)} ms). Verifica a Region da Render.")
        return False, steps
    if status == 200:
        add(True, f"{host} acessível (HTTP 200, {add_ms(t0)} ms)")
    elif status == 403 or "cloudfront" in body.lower():
        add(False, "A Bybit bloqueou este servidor (HTTP 403). A Render está numa região bloqueada (EUA): "
                   "cria o serviço na Region Frankfurt ou Singapore.")
        return False, steps
    else:
        add(False, f"{host} respondeu HTTP {status}: {body[:80]}")
        return False, steps

    ex = None
    try:
        ex = create_exchange(state)
    except ValueError as e:
        add(False, str(e))
        return False, steps
    try:
        t0 = time.time()
        await asyncio.wait_for(ex.load_markets(), 45)
        n = sum(1 for m in ex.markets.values() if m.get("swap") and m.get("linear") and m.get("quote") == "USDT")
        add(True, f"Mercados carregados: {n} contratos USDT ({add_ms(t0)} ms)")
        t0 = time.time()
        total, free = read_usdt(await asyncio.wait_for(ex.fetch_balance(), 25))
        add(True, f"Chave aceite ({mode_label(mode)}). Saldo {total:.4f} USDT (livre {free:.4f}) ({add_ms(t0)} ms)")
        if total <= 0:
            steps.append("• " + ZERO_HINT)
        return True, steps
    except Exception as e:
        add(False, explain_error(e, mode)[0])
        return False, steps
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
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return ("A Bybit não respondeu a tempo. Confirma que o serviço da Render está na Region Frankfurt "
                "ou Singapore (não nos EUA) e usa o botão Diagnóstico."), False
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
