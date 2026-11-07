import time
import ccxt

class ScalpingEngine:
    def __init__(self, exchange, pairs, leverage=21):
        self.exchange = exchange
        self.pairs = pairs
        self.leverage = leverage
        self.active_trade = None

    def set_leverage(self, symbol):
        try:
            # Configurar alavancagem cruzada e margem para futuros lineares USDT
            self.exchange.set_leverage(self.leverage, symbol)
        except Exception:
            pass

    def scan_best_market(self):
        """Varre os pares ativos e identifica o que tem melhor momento direcional e volume."""
        best_pair = None
        best_score = -999.0
        target_side = 'buy'

        for sym in self.pairs:
            try:
                ohlcv = self.exchange.fetch_ohlcv(sym, timeframe='1m', limit=5)
                if len(ohlcv) < 5:
                    continue
                
                # Extrair fechos para calcular variação de curto prazo (Momentum HFT)
                closes = [x[4] for x in ohlcv]
                volumes = [x[5] for x in ohlcv]
                
                # Variação percentual dos últimos minutos
                price_change = (closes[-1] - closes[0]) / closes[0]
                avg_volume = sum(volumes) / len(volumes)
                
                # Filtro de Saturação: Se o preço oscilou demais sem pausa, o mercado está saturado
                if abs(price_change) > 0.015:  # Mais de 1.5% num minuto indica exaustão/saturação
                    continue

                # Pontuação de direção baseada em momentum e volume
                score = abs(price_change) * avg_volume
                
                if score > best_score:
                    best_score = score
                    best_pair = sym
                    target_side = 'buy' if price_change > 0 else 'sell'
            except Exception:
                continue

        return best_pair, target_side

    def execute_scalp_loop(self, bot_state):
        """Ciclo principal de alta frequência, gestão de risco e trailing stop no cume."""
        while bot_state["running"]:
            try:
                ex = self.exchange
                if not ex:
                    time.sleep(1)
                    continue

                # 1. Se não houver posição ativa, procurar o melhor ativo livre de saturação
                if not self.active_trade:
                    bot_state["log"] = "A escanear mercado em busca de direção..."
                    pair, side = self.scan_best_market()
                    
                    if not pair:
                        bot_state["log"] = "Mercado saturado ou sem direção clara. A procurar..."
                        time.sleep(2)
                        continue

                    # Preparar e abrir ordem de alta frequência
                    self.set_leverage(pair)
                    ticker = ex.fetch_ticker(pair)
                    entry_price = ticker['ask'] if side == 'buy' else ticker['bid']
                    
                    # Calcular tamanho da ordem baseado no saldo disponível
                    balance_info = ex.fetch_balance()
                    usdt_free = float(balance_info.get('free', {}).get('USDT', 0.0))
                    
                    if usdt_free < 5.0:
                        bot_state["log"] = "Saldo insuficiente para operar."
                        time.sleep(5)
                        continue

                    amount_usdt = usdt_free * 0.95 * self.leverage  # Usar 95% do capital com alavancagem
                    amount_coins = amount_usdt / entry_price

                    # Executar ordem de mercado (Velocidade HFT)
                    order = ex.create_order(pair, 'market', side, amount_coins)
                    
                    self.active_trade = {
                        "pair": pair,
                        "side": side,
                        "entry_price": entry_price,
                        "amount": amount_coins,
                        "highest_price": entry_price,
                        "take_profit_target": entry_price * (1.004 if side == 'buy' else 0.996), # Alvo inicial +0.4%
                        "stop_loss": entry_price * (0.995 if side == 'buy' else 1.005)      # Stop inicial -0.5%
                    }
                    bot_state["active_position"] = self.active_trade
                    bot_state["log"] = f"Entrada executada em {pair} ({side.upper()}) a {entry_price}"

                # 2. Gestão em Tempo Real da Posição Ativa (Trailing Stop no Cume & Proteção de Inversão)
                else:
                    trade = self.active_trade
                    pair = trade["pair"]
                    side = trade["side"]
                    entry_price = trade["entry_price"]

                    ticker = ex.fetch_ticker(pair)
                    current_price = ticker['bid'] if side == 'buy' else ticker['ask']

                    # Atualizar o cume do lucro (Trailing Peak) em tempo real
                    if side == 'buy':
                        if current_price > trade["highest_price"]:
                            trade["highest_price"] = current_price
                            # O stop móvel fixa-se logo abaixo do cume para garantir lucro máximo
                            trade["stop_loss"] = current_price * 0.998  # Protege com margem de 0.2% do topo
                    else:
                        if current_price < trade["highest_price"]:
                            trade["highest_price"] = current_price
                            trade["stop_loss"] = current_price * 1.002

                    # Condições de fecho instantâneo (Take Profit, Trailing Hit ou Inversão Contrária)
                    should_close = False
                    close_reason = ""

                    if side == 'buy':
                        if current_price <= trade["stop_loss"]:
                            should_close = True
                            close_reason = "Trailing Stop / Proteção de Cume atingida"
                        elif current_price >= trade["entry_price"] * 1.008: # Alvo técnico de scalping rápido
                            should_close = True
                            close_reason = "Take Profit rápido atingido"
                    else:
                        if current_price >= trade["stop_loss"]:
                            should_close = True
                            close_reason = "Trailing Stop / Proteção de Cume atingida"
                        elif current_price <= trade["entry_price"] * 0.992:
                            should_close = True
                            close_reason = "Take Profit rápido atingido"

                    if should_close:
                        # Fechar posição imediatamente a mercado
                        close_side = 'sell' if side == 'buy' else 'buy'
                        ex.create_order(pair, 'market', close_side, trade["amount"])
                        
                        # Calcular PnL realizado
                        pnl = (current_price - entry_price) * trade["amount"] if side == 'buy' else (entry_price - current_price) * trade["amount"]
                        bot_state["realized_pnl"] += pnl
                        bot_state["log"] = f"Posição fechada: {close_reason}. PnL: {pnl:.4f} USDT"
                        
                        # Resetar posição para o scanner retomar imediatamente sem perder tempo
                        self.active_trade = None
                        bot_state["active_position"] = None

                time.sleep(0.5)  # Frequência de varredura ultrarrápida (HFT)
            except Exception as e:
                bot_state["log"] = f"Erro no ciclo HFT: str(e)[:30]"
                time.sleep(2)
