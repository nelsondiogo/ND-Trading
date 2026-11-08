# -*- coding: utf-8 -*-
"""
ND-SCALPING — motor de scalping (LONG e SHORT) para futuros perpétuos USDT da Bybit.

Duas camadas:
  1. SINCRONIZADOR (sempre ligado quando há chaves): lê saldo, preços ao vivo e sinais de todos os pares.
  2. ROBÔ (botão INICIAR): abre e gere operações. SL e TP ficam na Bybit; a partir do gatilho,
     STOP RÍGIDO no cume do melhor preço (qualquer recuo fecha de imediato).
Corre numa thread própria (ver app.py) e comunica com o painel através do dicionário `state`.
"""
import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import config as C
from exchange_management import create_exchange, explain_error, mode_label, read_usdt, ZERO_HINT

TZ = timezone(timedelta(hours=C.TZ_OFFSET_H))


def hms(ts=None):
    return datetime.fromtimestamp(ts or time.time(), TZ).strftime("%H:%M:%S")


def stamp(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%d/%m %H:%M:%S")


def fmt(x):
    s = f"{float(x):.8f}".rstrip("0").rstrip(".")
    return s or "0"


def push_log(state, msg):
    state["log"] = msg
    ev = state["events"]
    ev.insert(0, f"{hms()}  {msg}")
    del ev[60:]


def analyze(c):
    """Analisa velas de 1 min [ts, o, h, l, c, v] (a última está em formação).
    Devolve dict: trend (LONG|SHORT|NEUTRO), side (sinal pronto ou None), score, move, vr, chg1m, status."""
    res = {"side": None, "trend": "—", "score": 0.0, "move": 0.0, "vr": 0.0, "chg1m": 0.0, "status": "SEM DADOS"}
    if not c or len(c) < 24:
        return res
    cur, prev = c[-1], c[-2]
    hist = c[-22:-2]
    res["move"] = max((k[2] - k[3]) / k[3] * 100 for k in (cur, prev))
    avg = sum(k[5] for k in hist) / len(hist)
    res["vr"] = prev[5] / avg if avg > 0 else 0.0
    res["chg1m"] = (cur[4] - cur[1]) / cur[1] * 100 if cur[1] else 0.0

    c3, c2, c1 = c[-3][4], prev[4], cur[4]                 # três fechos seguidos
    trend = "LONG" if c1 > c2 > c3 else ("SHORT" if c1 < c2 < c3 else "NEUTRO")
    res["trend"] = res["status"] = trend
    if trend == "NEUTRO":
        return res
    if res["move"] > C.MAX_1M_MOVE_PCT:                    # anti-saturação (exaustão/topo)
        res["status"] = "SATURADO"
        return res
    if (trend == "LONG" and not C.ALLOW_LONG) or (trend == "SHORT" and not C.ALLOW_SHORT):
        res["status"] = "DESATIVADO"
        return res
    if res["vr"] < C.MIN_VOL_RATIO:
        res["status"] = "VOL BAIXO"
        return res
    res.update(side=trend.lower(), status="SINAL", score=res["vr"] * abs(c1 - c3) / c3 * 100)
    return res


class _Fatal(Exception):
    pass


class Engine:
    def __init__(self, ex, state, gen=0):
        self.ex = ex
        self.st = state
        self.gen = gen
        self.pairs = []
        self.tick_size = {}
        self.maxlev = {}
        self.min_cost = {}
        self.min_amt = {}
        self.tick = {}            # último ticker de cada par
        self.ana = {}             # última análise de cada par
        self.candidates = []
        self.scan_time = 0.0
        self.cooldown = {}
        self.lev_ok = set()
        self.loss_streak = 0
        self.pause_until = 0.0
        self.pnl_day = 0.0
        self.day = datetime.now(timezone.utc).date()
        self.day_balance = 0.0
        self.free = 0.0
        self.fatal_msg = ""
        self.recovered = False
        self.relaxed = state.get("mode") == "testnet"   # testnet: pouco volume e spreads largos
        self._warned = {}

    # ------------------------- utilitários -------------------------
    def log(self, msg):
        push_log(self.st, msg)

    def warn_once(self, key, msg, every=60):
        if time.time() - self._warned.get(key, 0) >= every:
            self._warned[key] = time.time()
            self.log(msg)

    def online(self):
        """A ligação deve continuar (há chaves, sem pedido de reconexão e sem erro fatal)."""
        return (bool(self.st["api_key"]) and not self.st["reconnect"] and not self.fatal_msg
                and self.st.get("gen", 0) == self.gen)

    def trading(self):
        """O robô pode operar (botão INICIAR ativo)."""
        return self.online() and self.st["running"]

    def step(self, msg):
        self.st["conn_step"] = msg

    def fail(self, msg):
        self.fatal_msg = msg
        self.log(msg)

    def halt_trading(self, msg):
        self.log(msg)
        self.st["running"] = False

    async def nap(self, secs):
        end = time.time() + secs
        while self.online() and time.time() < end:
            await asyncio.sleep(min(0.5, max(0.0, end - time.time())))

    def roll_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.day, self.pnl_day, self.day_balance = today, 0.0, self.st["balance"]

    # ------------------------- dimensionamento (saldo pequeno) -------------------------
    def lev_for(self, symbol):
        return max(1, min(int(self.st["leverage"]), self.maxlev.get(symbol, 999)))

    def margin_eff(self):
        """Margem realmente usada: a definida em Ajustes, limitada a BALANCE_USE_PCT do saldo livre."""
        return max(0.0, min(float(self.st["margin_usdt"]), self.free * C.BALANCE_USE_PCT / 100))

    def need_notional(self, symbol, price):
        return max(self.min_cost.get(symbol, C.MIN_NOTIONAL_FALLBACK), self.min_amt.get(symbol, 0.0) * price)

    def tradable(self, sym, t):
        """(ok, motivo). Filtros de execução do par neste momento."""
        price = t["last"]
        if not self.relaxed:
            if t["qv"] < C.MIN_QUOTE_VOLUME_24H:
                return False, "VOL 24H BAIXO"
            bid, ask = t.get("bid"), t.get("ask")
            if not bid or not ask or (ask - bid) / ask * 100 > C.MAX_SPREAD_PCT:
                return False, "SPREAD LARGO"
        if self.tick_size.get(sym, 0) / price * 100 > C.MAX_TICK_PCT:
            return False, "TICK GRANDE"
        need = self.need_notional(sym, price)
        if self.margin_eff() * self.lev_for(sym) < need * 1.02:
            return False, f"MÍN. ORDEM {need:.1f} USDT"
        return True, ""

    # ------------------------- arranque -------------------------
    async def prepare(self):
        ex = self.ex
        self.log(f"A ligar à Bybit ({mode_label(self.st['mode'])})...")
        self.step("1/3 a carregar os mercados")
        await asyncio.wait_for(ex.load_markets(), 45)
        missing = []
        for s in C.PAIRS:
            m = ex.markets.get(s)
            if m and m.get("swap") and m.get("linear") and m.get("active", True):
                self.pairs.append(s)
                lim = m.get("limits") or {}
                self.tick_size[s] = float((m.get("precision") or {}).get("price") or 0)
                mx = (lim.get("leverage") or {}).get("max")
                if mx:
                    self.maxlev[s] = int(float(mx))
                mc = float((lim.get("cost") or {}).get("min") or 0)
                self.min_cost[s] = mc if mc >= 1 else C.MIN_NOTIONAL_FALLBACK
                self.min_amt[s] = float((lim.get("amount") or {}).get("min") or 0)
            else:
                missing.append(s.split("/")[0])
        self.step("2/3 a ler o saldo (valida a chave)")
        await asyncio.wait_for(self.refresh_balance(), 25)          # valida a chave (autenticação)
        self.step("3/3 a preparar")
        try:
            await asyncio.wait_for(
                ex.set_margin_mode(C.MARGIN_MODE, "BTC/USDT:USDT", {"leverage": int(self.st["leverage"])}), 10)
        except Exception:
            pass                                        # já está em cross ou a conta não permite alterar
        self.st["conn"], self.st["conn_msg"], self.st["conn_step"] = "ligado", "", ""
        extra = f" | sem par nesta conta: {', '.join(missing)}" if missing else ""
        self.log(f"Ligado à Bybit. Saldo {self.st['balance']:.4f} USDT | {len(self.pairs)}/{len(C.PAIRS)} pares{extra}")
        if not self.pairs:
            self.log("Aviso: nenhum par da lista existe neste ambiente; a ligação está OK mas não há mercado para mostrar.")

    async def refresh_balance(self):
        total, free = read_usdt(await self.ex.fetch_balance())
        self.free = free
        self.st["balance"] = total
        self.st["free"] = free
        if not self.st["initial_balance"]:
            self.st["initial_balance"] = total
        if self.day_balance <= 0 and total > 0:
            self.day_balance = total
        if total <= 0:
            self.warn_once("zero", ZERO_HINT, every=300)

    async def run(self):
        await self.prepare()
        tasks = [asyncio.create_task(t) for t in (self.ticker_loop(), self.scanner(), self.trader(), self.balance_loop())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def balance_loop(self):
        while self.online():
            await self.nap(10)
            if not self.online():
                break
            try:
                await self.refresh_balance()
            except Exception as e:
                msg, fatal = explain_error(e, self.st["mode"])
                if fatal:
                    self.fail(msg)
                    return
                self.warn_once("bal", f"Saldo: {msg}")

    # ------------------- sincronizador: preços ao vivo e sinais -------------------
    async def ticker_loop(self):
        while self.online():
            try:
                if not self.pairs:
                    await self.nap(5)
                    continue
                tickers = await self.ex.fetch_tickers(self.pairs)
                for s in self.pairs:
                    t = tickers.get(s)
                    if t and (t.get("last") or 0) > 0:
                        self.tick[s] = {
                            "last": float(t["last"]), "bid": t.get("bid"), "ask": t.get("ask"),
                            "qv": float(t.get("quoteVolume") or 0), "pct": float(t.get("percentage") or 0),
                        }
                self.publish_market()
                self.st["last_update"] = hms()
            except Exception as e:
                msg, fatal = explain_error(e, self.st["mode"])
                if fatal:
                    self.fail(msg)
                    return
                self.warn_once("tick", f"Preços: {msg}")
            await self.nap(C.TICKER_INTERVAL_S)

    def publish_market(self):
        rows, counts = [], {"LONG": 0, "SHORT": 0, "NEUTRO": 0}
        for s in self.pairs:
            t = self.tick.get(s)
            if not t or not (0 < t["last"] < C.MAX_PRICE_USDT):
                continue
            a = self.ana.get(s, {})
            ok, why = self.tradable(s, t)
            st_ = a.get("status", "")
            if st_ in ("SATURADO", "VOL BAIXO", "DESATIVADO"):
                note = st_
            elif st_ == "SINAL":
                note = "SINAL ✓" if ok else why
            else:
                note = "" if ok else why
            bid, ask = t.get("bid"), t.get("ask")
            spread = (ask - bid) / ask * 100 if bid and ask else 0.0
            trend = a.get("trend", "—")
            if trend in counts:
                counts[trend] += 1
            rows.append({
                "pair": s.split("/")[0], "p": t["last"], "price": fmt(t["last"]),
                "chg24": round(t["pct"], 2), "chg1m": round(a.get("chg1m", 0.0), 3),
                "vr": round(a.get("vr", 0.0), 1), "spread": round(spread, 3),
                "vol24": f"{t['qv'] / 1e6:.1f}M", "trend": trend, "note": note, "qv": t["qv"],
            })
        rows.sort(key=lambda r: -r["qv"])
        self.st["market_data"] = rows
        self.st["market_counts"] = counts

    async def scan_once(self):
        uni = [(self.tick[s]["qv"], s) for s in self.pairs
               if s in self.tick and 0 < self.tick[s]["last"] < C.MAX_PRICE_USDT]   # só moedas < 1 USDT
        uni.sort(reverse=True)
        syms = [s for _, s in uni[:C.TOP_N]]
        res = await asyncio.gather(*(self.ex.fetch_ohlcv(s, "1m", limit=25) for s in syms), return_exceptions=True)
        if syms and all(isinstance(r, Exception) for r in res):
            raise res[0]
        cands = []
        for s, c in zip(syms, res):
            if isinstance(c, Exception):
                continue
            a = analyze(c)
            self.ana[s] = a
            if a["side"] and self.tradable(s, self.tick[s])[0]:
                cands.append((a["score"], s, a["side"]))
        cands.sort(reverse=True)
        self.candidates = cands
        self.st["scan_info"] = f"{len(uni)} moedas abaixo de {C.MAX_PRICE_USDT:g} USDT | {len(cands)} sinais prontos"
        self.publish_market()

    async def scanner(self):
        while self.online():
            try:
                if self.tick:
                    await self.scan_once()
                    self.scan_time = time.time()
            except Exception as e:
                msg, fatal = explain_error(e, self.st["mode"])
                if fatal:
                    self.fail(msg)
                    return
                self.warn_once("scan", f"Scanner: {msg}")
            await self.nap(C.SCAN_BUSY_S if self.st["active_position"] else C.SCAN_INTERVAL_S)

    def pick(self):
        if time.time() - self.scan_time > 15:            # dados velhos: não entra
            return None
        now = time.time()
        for _, s, side in self.candidates:
            if self.cooldown.get(s, 0) < now:
                return s, side
        return None

    # ------------------------- ordens e posição -------------------------
    async def get_position(self, symbol):
        """Dict da posição aberta ou None se estiver fechada."""
        for p in await self.ex.fetch_positions([symbol]):
            size = float(p.get("contracts") or 0)
            if size > 0:
                return {"entry": float(p["entryPrice"]), "size": size, "side": p.get("side")}
        return None

    async def set_stop(self, symbol, **kw):
        """Define/atualiza SL e/ou TP diretamente na Bybit."""
        params = {
            "category": "linear",
            "symbol": self.ex.market(symbol)["id"],
            "tpslMode": "Full",
            "positionIdx": 0,
        }
        for k, v in kw.items():
            params[k] = self.ex.price_to_precision(symbol, v)
        try:
            await self.ex.private_post_v5_position_trading_stop(params)
        except Exception as e:
            if "34040" in str(e) or "not modified" in str(e).lower():
                return
            raise

    async def close(self, symbol, motivo):
        for _ in range(3):
            pos = await self.get_position(symbol)
            if not pos:
                return
            close_side = "sell" if pos["side"] == "long" else "buy"
            try:
                await self.ex.create_order(symbol, "market", close_side, pos["size"],
                                           None, {"reduceOnly": True})
                return
            except Exception:
                await asyncio.sleep(0.3)
        raise RuntimeError(f"Não consegui fechar {symbol}")

    async def realized_pnl(self, symbol, d, entry, size, last):
        try:
            r = await self.ex.private_get_v5_position_closed_pnl({
                "category": "linear",
                "symbol": self.ex.market(symbol)["id"],
                "limit": 1,
            })
            return float(r["result"]["list"][0]["closedPnl"])
        except Exception:
            cs = self.ex.market(symbol).get("contractSize") or 1
            return d * (last - entry) * size * cs        # estimativa sem taxas

    # ------------------------- operação -------------------------
    async def trade(self, symbol, side):
        ex = self.ex
        m = ex.market(symbol)
        d = 1 if side == "long" else -1
        coin = symbol.split("/")[0]

        c = await ex.fetch_ohlcv(symbol, "1m", limit=25)   # revalida o sinal mesmo antes de entrar
        if analyze(c)["side"] != side:
            return

        lev = self.lev_for(symbol)                         # respeita o máximo do contrato
        margin = self.margin_eff()                         # saldo pequeno: no máx. 90% do saldo livre
        price = c[-1][4]
        need = self.need_notional(symbol, price)
        if margin * lev < need * 1.02:
            self.warn_once("min", f"Saldo insuficiente: a ordem mínima de {coin} é {need:.1f} USDT; "
                                  f"com {lev}x e {margin:.2f} USDT de margem só dá {margin * lev:.2f} USDT.")
            self.cooldown[symbol] = time.time() + 120
            return

        if (symbol, lev) not in self.lev_ok:
            try:
                await ex.set_leverage(lev, symbol)
            except Exception as e:
                if "110043" not in str(e) and "not modified" not in str(e).lower():
                    self.log(f"Alavancagem {coin}: {str(e)[:80]}")
                    self.cooldown[symbol] = time.time() + 900
                    return
            self.lev_ok.add((symbol, lev))

        amount = float(ex.amount_to_precision(symbol, margin * lev / price))
        if amount <= 0 or amount < self.min_amt.get(symbol, 0) or amount * price < need:
            self.log(f"{coin}: tamanho abaixo do mínimo do contrato com a margem atual")
            self.cooldown[symbol] = time.time() + 600
            return

        await ex.create_order(symbol, "market", "buy" if d > 0 else "sell", amount)
        t_open = time.time()

        pos = None
        for _ in range(10):
            try:
                pos = await self.get_position(symbol)
            except Exception:
                pos = None
            if pos:
                break
            await asyncio.sleep(0.15)
        if not pos:
            self.log(f"{coin}: posição não confirmada — VERIFICA A BYBIT")
            self.cooldown[symbol] = time.time() + 600
            return
        entry, size = pos["entry"], pos["size"]

        sl = entry * (1 - d * C.SL_PCT / 100)              # long: abaixo | short: acima
        tp = entry * (1 + d * C.TP_PCT / 100)              # long: acima  | short: abaixo
        try:
            await self.set_stop(symbol, stopLoss=sl, takeProfit=tp)
        except Exception as e:
            self.log(f"SL/TP falhou ({str(e)[:60]}) — a fechar por segurança")
            await self.close(symbol, "sem proteção")
            return
        self.log(f"ENTRADA {side.upper()} {coin} @ {fmt(entry)} | SL {fmt(sl)} | TP {fmt(tp)} | {lev}x | margem {margin:.4f}")
        await self.manage(symbol, d, entry, size, sl, tp, entry, lev, t_open)

    async def manage(self, symbol, d, entry, size, last_sl, tp, best, lev, opened_ts=None):
        """Gere a posição até fechar. d=+1 long, d=-1 short.
        best = melhor preço atingido (máximo no long, mínimo no short)."""
        ex = self.ex
        coin = symbol.split("/")[0]
        side_txt = "LONG" if d > 0 else "SHORT"
        mk = ex.market(symbol)
        tick = float((mk.get("precision") or {}).get("price") or 0)
        if tick <= 0:
            tick = entry * 1e-4
        t0 = opened_ts or time.time()
        trailing = False
        reason = "SL/TP na Bybit"
        p, window, last_check, fails = best, deque(), 0.0, 0
        chart = {"pair": coin, "side": side_txt, "entry": entry, "sl": last_sl, "tp": tp,
                 "points": [], "closed": False, "trailing": False}
        pts = chart["points"]
        self.st["chart"] = chart

        while True:
            await asyncio.sleep(C.POLL_INTERVAL_S)

            if not self.trading():                         # PARAR ROBÔ / reconexão: fecha a posição
                reason = "Reconexão" if self.st["reconnect"] else "Robô parado"
                try:
                    await self.close(symbol, reason)
                except Exception as e:
                    self.log(f"ATENÇÃO: falha ao fechar {coin} ({str(e)[:50]}) — verifica a Bybit")
                break

            try:
                p = (await ex.fetch_ticker(symbol))["last"]
                now = time.time()
                if now - last_check >= 1.0:
                    last_check = now
                    if await self.get_position(symbol) is None:      # SL/TP disparou na Bybit
                        reason = "Stop loss (Bybit)" if d * (p - entry) < 0 else "Alvo/stop no cume (Bybit)"
                        break
                fails = 0
            except Exception as e:
                fails += 1
                if fails % 20 == 0:
                    self.log(f"{coin}: sem dados da Bybit ({explain_error(e, self.st['mode'])[0][:50]})")
                continue

            if d * (p - best) > 0:
                best = p
            window.append((now, p))
            while window and now - window[0][0] > C.REVERSAL_WINDOW_S:
                window.popleft()

            pts.append([round(now - t0, 1), p])
            if len(pts) > C.CHART_POINTS:
                del pts[0]
            chart["sl"], chart["trailing"] = last_sl, trailing
            self.st["active_position"] = {
                "pair": coin, "side": side_txt, "entry": fmt(entry), "price": fmt(p),
                "pnl_pct": round(d * (p - entry) / entry * 100, 3),
                "sl": fmt(last_sl), "tp": fmt(tp), "trailing": trailing,
            }

            # Stop "Dinamite": a partir do gatilho, STOP RÍGIDO no cume do melhor preço
            if not trailing and d * (best - entry) / entry * 100 >= C.TRAIL_TRIGGER_PCT:
                trailing = True
                self.log(f"DINAMITE ativado em {coin}: stop rígido no cume {fmt(best)}")
            if trailing:
                level = best * (1 - d * C.TRAIL_DISTANCE_PCT / 100)    # 0% = exatamente o cume
                if d * (p - level) < 0:                                # qualquer tick contra => fecha já
                    reason = "Stop rígido (recuo do cume)"
                    await self.close(symbol, reason)
                    break
                new_sl = level - d * tick       # na Bybit: 1 tick além do cume (cobre entre leituras)
                if d * (new_sl - last_sl) > tick * 0.5:
                    try:
                        await self.set_stop(symbol, stopLoss=new_sl)
                        last_sl = new_sl
                    except Exception as e:
                        self.log(f"SL no cume não aplicado ({str(e)[:50]}) — a fechar")
                        reason = "Stop rígido: SL não aplicado"
                        await self.close(symbol, reason)
                        break
            else:
                # Antes da Dinamite: proteção de inversão brusca dentro da janela
                ref = max(x for _, x in window) if d > 0 else min(x for _, x in window)
                if d * (ref - p) / ref * 100 >= C.REVERSAL_DROP_PCT:
                    reason = "Inversão brusca"
                    await self.close(symbol, reason)
                    break

        await asyncio.sleep(1.0)
        pnl = await self.realized_pnl(symbol, d, entry, size, p)
        closed_ts = time.time()
        cs = mk.get("contractSize") or 1
        notional = size * entry * cs
        margin_used = notional / max(1, lev)
        self.pnl_day += pnl
        self.st["realized_pnl"] += pnl
        self.st["active_position"] = None
        chart.update(closed=True, exit=p, pnl=round(pnl, 4))

        hist = self.st["history"]
        hist.insert(0, {
            "opened": stamp(t0), "closed": stamp(closed_ts), "dur": int(closed_ts - t0),
            "pair": coin, "side": side_txt, "entry": fmt(entry), "exit": fmt(p),
            "qty": size, "notional": round(notional, 4), "margin": round(margin_used, 4),
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl / margin_used * 100, 2) if margin_used > 0 else 0.0,   # sobre a margem
            "price_pct": round(d * (p - entry) / entry * 100, 3),                       # movimento do preço
            "reason": reason,
        })
        del hist[C.HISTORY_MAX:]
        cb = self.st.get("history_cb")
        if cb:
            try:
                cb(hist)
            except Exception:
                pass
        self.log(f"FIM {side_txt} {coin} | {reason} | PnL {pnl:+.4f} USDT")

        self.cooldown[symbol] = time.time() + (C.COOLDOWN_LOSS_S if pnl < 0 else C.COOLDOWN_S)
        if pnl < 0:
            self.loss_streak += 1
            if self.loss_streak >= C.MAX_CONSEC_LOSSES:
                self.pause_until = time.time() + C.PAUSE_AFTER_LOSSES_S
                self.loss_streak = 0
                self.log(f"{C.MAX_CONSEC_LOSSES} perdas seguidas: pausa de {C.PAUSE_AFTER_LOSSES_S // 60} min")
        else:
            self.loss_streak = 0
        try:
            await self.refresh_balance()
        except Exception:
            pass

    async def recover(self):
        """Ao ligar o robô, retoma a gestão de posições já abertas nos pares da lista."""
        try:
            poss = await self.ex.fetch_positions(None, {"subType": "linear", "settleCoin": "USDT"})
        except Exception:
            return
        for p in poss:
            size = float(p.get("contracts") or 0)
            sym = p.get("symbol")
            if size <= 0 or sym not in self.pairs or not self.trading():
                continue
            entry = float(p["entryPrice"])
            d = 1 if p.get("side") == "long" else -1
            tp = entry * (1 + d * C.TP_PCT / 100)
            last_sl = float(p.get("stopLossPrice") or 0)
            if last_sl <= 0:
                last_sl = entry * (1 - d * C.SL_PCT / 100)
                await self.set_stop(sym, stopLoss=last_sl, takeProfit=tp)
            last = (await self.ex.fetch_ticker(sym))["last"]
            best = last if d * (last - entry) > 0 else entry
            self.log(f"Posição existente retomada: {sym.split('/')[0]} {'LONG' if d > 0 else 'SHORT'}")
            await self.manage(sym, d, entry, size, last_sl, tp, best, self.lev_for(sym))

    async def trader(self):
        while self.online():
            if not self.st["running"]:                     # só sincroniza; não abre operações
                self.recovered = False
                await self.nap(1)
                continue
            if not self.recovered:
                self.recovered = True
                try:
                    await self.recover()
                except Exception as e:
                    self.warn_once("rec", f"Recuperação de posições: {explain_error(e, self.st['mode'])[0]}")
                continue
            self.roll_day()
            limit = self.day_balance * C.MAX_DAILY_LOSS_PCT / 100
            if self.day_balance > 0 and self.pnl_day <= -limit:
                self.halt_trading(f"Limite de perda diária atingido ({self.pnl_day:.4f} USDT = "
                                  f"{C.MAX_DAILY_LOSS_PCT:g}% do saldo). Entradas paradas até amanhã.")
                continue
            if time.time() < self.pause_until:
                await self.nap(1)
                continue
            pick = self.pick()
            if not pick:
                await asyncio.sleep(0.2)
                continue
            sym, side = pick
            try:
                await self.trade(sym, side)
            except Exception as e:
                msg, fatal = explain_error(e, self.st["mode"])
                self.log(f"Erro em {sym.split('/')[0]}: {msg}")
                try:
                    await self.close(sym, "erro")
                except Exception:
                    self.log("ATENÇÃO: não consegui fechar a posição — verifica a Bybit manualmente!")
                if fatal:
                    self.fail(msg)
                    return
                await self.nap(1)


async def _heartbeat(state, gen):
    """Batimento do motor: o painel usa-o para saber se o motor está vivo."""
    while state.get("gen", 0) == gen:
        state["heartbeat"] = time.time()
        await asyncio.sleep(1)


async def supervisor(state):
    """Mantém a ligação à Bybit sempre que há chaves (saldo, preços, sinais) e reage aos erros."""
    gen = state.get("gen", 0)
    hb = asyncio.create_task(_heartbeat(state, gen))
    try:
        while state.get("gen", 0) == gen:
            if not (state["api_key"] and state["api_secret"]):
                state["conn"], state["conn_msg"], state["conn_step"] = "sem_chaves", "", ""
                await asyncio.sleep(1)
                continue
            state["reconnect"] = False
            state["retry"] = False
            state["conn"], state["conn_msg"], state["conn_step"] = "a_ligar", "", "a iniciar"
            state["conn_since"] = time.time()
            ex = None
            wait = 0
            try:
                ex = create_exchange(state)
                eng = Engine(ex, state, gen)
                await eng.run()
                if eng.fatal_msg:
                    raise _Fatal(eng.fatal_msg)
            except _Fatal as e:
                state["conn"], state["conn_msg"], state["running"], wait = "erro", str(e), False, 60
            except Exception as e:
                msg, fatal = explain_error(e, state.get("mode"))
                push_log(state, msg)
                state["conn"], state["conn_msg"], state["conn_step"] = "erro", msg, ""
                if fatal:
                    state["running"], wait = False, 60
                else:
                    wait = 10
            finally:
                state["active_position"] = None
                if ex is not None:
                    try:
                        await ex.close()
                    except Exception:
                        pass
            for _ in range(wait):                          # espera antes de voltar a tentar
                if (state["retry"] or state["reconnect"] or state.get("gen", 0) != gen
                        or not (state["api_key"] and state["api_secret"])):
                    break
                await asyncio.sleep(1)
    finally:
        hb.cancel()
