# -*- coding: utf-8 -*-
"""
ND-SCALPING — motor de scalping (LONG e SHORT) para futuros perpétuos USDT da Bybit.

- Scanner contínuo em segundo plano (moedas abaixo de 1 USDT, lista em config.py).
- SL e TP ficam na própria Bybit (a posição continua protegida se o servidor cair).
- A partir do gatilho, STOP RÍGIDO no cume do melhor preço: qualquer recuo fecha de imediato.
- Corre numa thread própria (ver app.py); comunica com o painel através do dicionário `state`.
"""
import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import config as C
from exchange_management import create_exchange, explain_error, mode_label

TZ = timezone(timedelta(hours=C.TZ_OFFSET_H))


def hms():
    return datetime.now(TZ).strftime("%H:%M:%S")


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
    Devolve dict: side ('long'|'short'|None), score, move (amplitude %), vr (volume x média), status."""
    res = {"side": None, "score": 0.0, "move": 0.0, "vr": 0.0, "status": "SEM DADOS"}
    if not c or len(c) < 24:
        return res
    cur, prev = c[-1], c[-2]
    hist = c[-22:-2]
    res["move"] = max((k[2] - k[3]) / k[3] * 100 for k in (cur, prev))
    avg = sum(k[5] for k in hist) / len(hist)
    res["vr"] = prev[5] / avg if avg > 0 else 0.0
    res["status"] = "NEUTRO"

    if res["move"] > C.MAX_1M_MOVE_PCT:                 # anti-saturação (exaustão/topo)
        res["status"] = "SATURADO"
        return res

    c3, c2, c1 = c[-3][4], prev[4], cur[4]              # três fechos seguidos
    if c1 > c2 > c3 and C.ALLOW_LONG:
        side = "long"
    elif c1 < c2 < c3 and C.ALLOW_SHORT:
        side = "short"
    else:
        return res

    if res["vr"] < C.MIN_VOL_RATIO:
        res["status"] = "VOL BAIXO"
        return res
    res.update(side=side, score=res["vr"] * abs(c1 - c3) / c3 * 100, status=side.upper())
    return res


class Engine:
    def __init__(self, ex, state):
        self.ex = ex
        self.st = state
        self.pairs = []
        self.ticks = {}
        self.maxlev = {}
        self.candidates = []
        self.scan_time = 0.0
        self.cooldown = {}
        self.lev_ok = set()
        self.loss_streak = 0
        self.pause_until = 0.0
        self.pnl_day = 0.0
        self.day = datetime.now(timezone.utc).date()
        self.free = 0.0
        self.halted = False
        self.relaxed = state.get("mode") == "testnet"   # testnet: pouco volume e spreads largos
        self._warned = {}

    # ------------------------- utilitários -------------------------
    def log(self, msg):
        push_log(self.st, msg)

    def warn_once(self, key, msg, every=60):
        if time.time() - self._warned.get(key, 0) >= every:
            self._warned[key] = time.time()
            self.log(msg)

    def alive(self):
        return self.st["running"] and not self.st["reconnect"]

    def halt(self, msg):
        self.halted = True
        self.log(msg)
        self.st["running"] = False

    async def nap(self, secs):
        end = time.time() + secs
        while self.alive() and time.time() < end:
            await asyncio.sleep(min(0.5, max(0.0, end - time.time())))

    def roll_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.day, self.pnl_day = today, 0.0

    # ------------------------- arranque -------------------------
    async def prepare(self):
        ex = self.ex
        self.log(f"A ligar à Bybit ({mode_label(self.st['mode'])})...")
        await ex.load_markets()
        missing = []
        for s in C.PAIRS:
            m = ex.markets.get(s)
            if m and m.get("swap") and m.get("linear") and m.get("active", True):
                self.pairs.append(s)
                self.ticks[s] = float((m.get("precision") or {}).get("price") or 0)
                mx = ((m.get("limits") or {}).get("leverage") or {}).get("max")
                if mx:
                    self.maxlev[s] = int(float(mx))
            else:
                missing.append(s.split("/")[0])
        if not self.pairs:
            raise ValueError("Nenhum par da lista existe neste ambiente da Bybit.")
        await self.refresh_balance()                    # valida a chave (autenticação)
        try:
            await ex.set_margin_mode(C.MARGIN_MODE, "BTC/USDT:USDT", {"leverage": int(self.st["leverage"])})
        except Exception:
            pass                                        # já está em cross ou a conta não permite alterar
        extra = f" | sem par nesta conta: {', '.join(missing)}" if missing else ""
        self.log(f"Ligado. {len(self.pairs)}/{len(C.PAIRS)} pares ativos{extra}")

    async def refresh_balance(self):
        b = await self.ex.fetch_balance()
        total = float((b.get("total") or {}).get("USDT") or 0)
        free = float((b.get("free") or {}).get("USDT") or 0)
        self.free = free
        self.st["balance"] = total
        self.st["free"] = free
        if not self.st["initial_balance"]:
            self.st["initial_balance"] = total

    async def run(self):
        await self.prepare()
        tasks = [asyncio.create_task(t) for t in (self.scanner(), self.trader(), self.balance_loop())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def balance_loop(self):
        while self.alive():
            await self.nap(10)
            if not self.alive():
                break
            try:
                await self.refresh_balance()
            except Exception as e:
                msg, fatal = explain_error(e, self.st["mode"])
                if fatal:
                    self.halt(msg)
                    return
                self.warn_once("bal", f"Saldo: {msg}")

    # ------------------- scanner (segundo plano) -------------------
    async def scan_once(self):
        tickers = await self.ex.fetch_tickers(self.pairs)
        pool = []
        for sym in self.pairs:
            t = tickers.get(sym)
            if not t:
                continue
            price = t.get("last") or 0
            if price <= 0 or price >= C.MAX_PRICE_USDT:            # só moedas abaixo de 1 USDT
                continue
            qv = t.get("quoteVolume") or 0
            if not self.relaxed:
                if qv < C.MIN_QUOTE_VOLUME_24H:
                    continue
                bid, ask = t.get("bid"), t.get("ask")
                if not bid or not ask or (ask - bid) / ask * 100 > C.MAX_SPREAD_PCT:
                    continue                                       # spread largo come o stop
            if self.ticks.get(sym, 0) / price * 100 > C.MAX_TICK_PCT:
                continue                                           # tick grande demais para o preço
            pool.append((qv, sym))
        pool.sort(reverse=True)
        syms = [s for _, s in pool[:C.TOP_N]]
        res = await asyncio.gather(
            *(self.ex.fetch_ohlcv(s, "1m", limit=25) for s in syms),
            return_exceptions=True,
        )
        cands, market = [], []
        for s, c in zip(syms, res):
            if isinstance(c, Exception):
                continue
            a = analyze(c)
            market.append({
                "pair": s.split("/")[0], "price": fmt(c[-1][4]),
                "move": f"{a['move']:.2f}", "vr": f"{a['vr']:.1f}", "status": a["status"],
            })
            if a["side"]:
                cands.append((a["score"], s, a["side"]))
        cands.sort(reverse=True)
        self.st["market_data"] = market
        self.st["scan_info"] = f"{len(pool)}/{len(self.pairs)} pares elegíveis"
        return cands

    async def scanner(self):
        while self.alive():
            try:
                self.candidates = await self.scan_once()
                self.scan_time = time.time()
                self.st["last_update"] = hms()
            except Exception as e:
                msg, fatal = explain_error(e, self.st["mode"])
                if fatal:
                    self.halt(msg)
                    return
                self.warn_once("scan", f"Scanner: {msg}")
            await self.nap(C.SCAN_INTERVAL_S)

    def pick(self):
        if time.time() - self.scan_time > 6:             # dados velhos: não entra
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

        lev = int(self.st["leverage"])
        lev = min(lev, self.maxlev.get(symbol, lev))       # respeita o máximo do contrato
        margin = float(self.st["margin_usdt"])
        if self.free < margin * 1.05:
            self.warn_once("free", f"Saldo livre insuficiente ({self.free:.2f} USDT) para margem de {margin:.2f} USDT.")
            await self.nap(5)
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

        price = c[-1][4]
        amount = float(ex.amount_to_precision(symbol, margin * lev / price))
        min_amt = ((m.get("limits") or {}).get("amount") or {}).get("min") or 0
        if amount <= 0 or amount < min_amt:
            self.log(f"{coin}: margem insuficiente para o tamanho mínimo do contrato")
            self.cooldown[symbol] = time.time() + 3600
            return

        await ex.create_order(symbol, "market", "buy" if d > 0 else "sell", amount)

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
        self.log(f"ENTRADA {side.upper()} {coin} @ {fmt(entry)} | SL {fmt(sl)} | TP {fmt(tp)} | {lev}x")
        await self.manage(symbol, d, entry, size, sl, tp, entry)

    async def manage(self, symbol, d, entry, size, last_sl, tp, best):
        """Gere a posição até fechar. d=+1 long, d=-1 short.
        best = melhor preço atingido (máximo no long, mínimo no short)."""
        ex = self.ex
        coin = symbol.split("/")[0]
        side_txt = "LONG" if d > 0 else "SHORT"
        tick = float((ex.market(symbol).get("precision") or {}).get("price") or 0)
        if tick <= 0:
            tick = entry * 1e-4
        trailing = False
        reason = "SL/TP na Bybit"
        p, window, last_check, fails = best, deque(), 0.0, 0

        while True:
            await asyncio.sleep(C.POLL_INTERVAL_S)

            if not self.alive():                           # PARAR ROBÔ / reconexão: fecha a posição
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
        self.pnl_day += pnl
        self.st["realized_pnl"] += pnl
        self.st["active_position"] = None
        hist = self.st["history"]
        hist.insert(0, {
            "time": hms(), "pair": coin, "side": side_txt, "entry": fmt(entry),
            "exit": fmt(p), "pnl": round(pnl, 4), "reason": reason,
        })
        del hist[100:]
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
        """Após reinício (deploy), retoma a gestão de posições já abertas nos pares da lista."""
        try:
            poss = await self.ex.fetch_positions(None, {"subType": "linear", "settleCoin": "USDT"})
        except Exception:
            return
        for p in poss:
            size = float(p.get("contracts") or 0)
            sym = p.get("symbol")
            if size <= 0 or sym not in self.pairs or not self.alive():
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
            await self.manage(sym, d, entry, size, last_sl, tp, best)

    async def trader(self):
        try:
            await self.recover()
        except Exception as e:
            self.warn_once("rec", f"Recuperação de posições: {explain_error(e, self.st['mode'])[0]}")
        while self.alive():
            self.roll_day()
            if self.pnl_day <= -C.MAX_DAILY_LOSS_USDT:
                self.halt(f"Limite de perda diária atingido ({self.pnl_day:.2f} USDT). Robô parado.")
                return
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
                    self.halt(msg)
                    return
                await self.nap(1)


async def supervisor(state):
    """Liga/desliga o motor conforme o botão do painel e reage a erros de ligação."""
    while True:
        if not state["running"]:
            await asyncio.sleep(1)
            continue
        state["reconnect"] = False
        ex = None
        try:
            ex = create_exchange(state)
            eng = Engine(ex, state)
            await eng.run()
            if not eng.halted and not state["reconnect"]:
                push_log(state, "Robô parado.")
        except Exception as e:
            msg, fatal = explain_error(e, state.get("mode"))
            push_log(state, msg)
            if fatal:
                state["running"] = False
            else:
                for _ in range(10):
                    if not state["running"] or state["reconnect"]:
                        break
                    await asyncio.sleep(1)
        finally:
            state["active_position"] = None
            if ex is not None:
                try:
                    await ex.close()
                except Exception:
                    pass
