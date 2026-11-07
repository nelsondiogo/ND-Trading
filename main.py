import time
import threading
import datetime
import ccxt
from flask import Flask, render_template_string, request, redirect, url_for, jsonify

app = Flask(__name__)

# ============================== ESTADO GLOBAL ==============================
bot_state = {
    "running": False,
    "api_key": "",
    "api_secret": "",
    "is_demo": True,          # True = Testnet | False = conta REAL (mainnet)
    "leverage": 21,
    "initial_balance": 0.0,
    "balance": 0.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "market_data": [],
    "history": [],
    "last_update": "Aguardando...",
    "log": "Sistema pronto. Insira as credenciais em Ajustes."
}

# Moedas USDT Lineares abaixo de 1 USDT (Bybit perpetuals)
PAIRS = [
    'PEPE/USDT:USDT', 'SHIB/USDT:USDT', 'BONK/USDT:USDT', 'FLOKI/USDT:USDT',
    'DOGE/USDT:USDT', 'XRP/USDT:USDT', 'TRX/USDT:USDT', 'ADA/USDT:USDT'
]

MIN_NOTIONAL = 5.0   # mínimo da Bybit para futuros lineares

global_exchange = None
engine = None
engine_thread = None

# ============================== EXCHANGE ==============================
def get_exchange():
    global global_exchange
    key = bot_state["api_key"].strip()
    secret = bot_state["api_secret"].strip()

    if not key or not secret:
        return None

    if global_exchange is None:
        try:
            config = {
                'apiKey': key,
                'secret': secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'linear',
                    'adjustForTimeDifference': True,
                }
            }
            ex = ccxt.bybit(config)

            # Apenas sandbox mode. NUNCA sobrescrever urls['api'] manualmente.
            if bot_state["is_demo"]:
                ex.set_sandbox_mode(True)

            ex.load_markets()
            ex.fetch_balance()  # valida autenticação imediatamente
            global_exchange = ex
            bot_state["log"] = "Conexão Bybit estabelecida."
        except Exception:
            modo = "TESTNET" if bot_state["is_demo"] else "REAL (mainnet)"
            bot_state["log"] = (f"Falha na autenticação {modo}. Confirme que as chaves "
                                f"são deste ambiente e têm permissão de 'Contract/Derivatives - Trade'.")
            global_exchange = None
    return global_exchange


def get_usdt_balance(ex):
    """Saldo USDT robusto: tenta UNIFIED, depois CONTRACT, depois padrão."""
    attempts = [{'accountType': 'UNIFIED'}, {'accountType': 'CONTRACT'}, {}]
    for params in attempts:
        try:
            bal = ex.fetch_balance(params) if params else ex.fetch_balance()
            usdt = bal.get('USDT') or {}
            total = usdt.get('total') or bal.get('total', {}).get('USDT') or 0.0
            if float(total) > 0:
                return float(total)
        except Exception:
            continue
    return 0.0

# ============================== MOTOR SCALPING ==============================
class ScalpingEngine:
    def __init__(self, exchange, pairs, leverage=21):
        self.exchange = exchange
        self.pairs = pairs
        self.leverage = leverage
        self.active_trade = None
        self.lev_configured = set()

    def set_leverage(self, symbol):
        if symbol in self.lev_configured:
            return
        try:
            self.exchange.set_leverage(self.leverage, symbol)
            self.lev_configured.add(symbol)
        except Exception:
            try:
                self.exchange.set_margin_mode('cross', symbol)
                self.exchange.set_leverage(self.leverage, symbol)
                self.lev_configured.add(symbol)
            except Exception:
                pass

    def scan_best_market(self):
        best_pair, best_score, target_side = None, -999.0, 'buy'
        for sym in self.pairs:
            try:
                ohlcv = self.exchange.fetch_ohlcv(sym, timeframe='1m', limit=5)
                if len(ohlcv) < 5:
                    continue
                closes = [x[4] for x in ohlcv]
                volumes = [x[5] for x in ohlcv]
                price_change = (closes[-1] - closes[0]) / closes[0]
                avg_volume = sum(volumes) / len(volumes)

                if abs(price_change) > 0.015:  # saturação
                    continue

                score = abs(price_change) * avg_volume
                if score > best_score:
                    best_score = score
                    best_pair = sym
                    target_side = 'buy' if price_change > 0 else 'sell'
            except Exception:
                continue
        return best_pair, target_side

    def execute_scalp_loop(self, bot_state):
        while bot_state["running"]:
            try:
                ex = self.exchange
                if not ex:
                    time.sleep(1)
                    continue

                # ---------- 1. SEM POSIÇÃO: procurar entrada ----------
                if not self.active_trade:
                    bot_state["log"] = "A escanear mercado..."
                    pair, side = self.scan_best_market()
                    if not pair:
                        bot_state["log"] = "Sem direção clara. A procurar..."
                        time.sleep(2)
                        continue

                    self.set_leverage(pair)
                    ticker = ex.fetch_ticker(pair)
                    if side == 'buy':
                        entry_price = ticker.get('ask') or ticker.get('last')
                    else:
                        entry_price = ticker.get('bid') or ticker.get('last')

                    balance = get_usdt_balance(ex)
                    if balance < 6.0:
                        bot_state["log"] = f"Saldo insuficiente ({balance:.2f} USDT)."
                        time.sleep(5)
                        continue

                    amount_usdt = balance * 0.90 * self.leverage
                    amount = float(ex.amount_to_precision(pair, amount_usdt / entry_price))

                    if amount * entry_price < MIN_NOTIONAL:
                        bot_state["log"] = "Ordem abaixo do mínimo (5 USDT)."
                        time.sleep(2)
                        continue

                    ex.create_order(pair, 'market', side, amount)

                    self.active_trade = {
                        "pair": pair, "side": side, "entry_price": entry_price,
                        "amount": amount, "highest_price": entry_price,
                        "stop_loss": entry_price * (0.995 if side == 'buy' else 1.005),
                    }
                    bot_state["active_position"] = dict(self.active_trade)
                    bot_state["log"] = f"Entrada em {pair} ({side.upper()}) a {entry_price}"

                # ---------- 2. COM POSIÇÃO: gestão em tempo real ----------
                else:
                    trade = self.active_trade
                    pair, side, entry_price = trade["pair"], trade["side"], trade["entry_price"]

                    ticker = ex.fetch_ticker(pair)
                    if side == 'buy':
                        current_price = ticker.get('bid') or ticker.get('last')
                    else:
                        current_price = ticker.get('ask') or ticker.get('last')

                    # Trailing stop no cume
                    if side == 'buy':
                        if current_price > trade["highest_price"]:
                            trade["highest_price"] = current_price
                            trade["stop_loss"] = current_price * 0.998
                    else:
                        if current_price < trade["highest_price"]:
                            trade["highest_price"] = current_price
                            trade["stop_loss"] = current_price * 1.002
                    bot_state["active_position"] = dict(trade)

                    should_close, close_reason = False, ""
                    if side == 'buy':
                        if current_price <= trade["stop_loss"]:
                            should_close, close_reason = True, "Trailing Stop"
                        elif current_price >= entry_price * 1.008:
                            should_close, close_reason = True, "Take Profit"
                    else:
                        if current_price >= trade["stop_loss"]:
                            should_close, close_reason = True, "Trailing Stop"
                        elif current_price <= entry_price * 0.992:
                            should_close, close_reason = True, "Take Profit"

                    if should_close:
                        close_side = 'sell' if side == 'buy' else 'buy'
                        ex.create_order(pair, 'market', close_side, trade["amount"],
                                        params={'reduceOnly': True})

                        pnl = ((current_price - entry_price) if side == 'buy'
                               else (entry_price - current_price)) * trade["amount"]
                        bot_state["realized_pnl"] += pnl
                        bot_state["history"].insert(0, {
                            "time": datetime.datetime.now().strftime("%H:%M:%S"),
                            "pair": pair.split('/')[0], "side": side,
                            "pnl": pnl, "reason": close_reason
                        })
                        bot_state["history"] = bot_state["history"][:30]
                        bot_state["log"] = f"Fechado: {close_reason}. PnL: {pnl:.4f} USDT"
                        self.active_trade = None
                        bot_state["active_position"] = None

                time.sleep(0.5)
            except Exception as e:
                bot_state["log"] = f"Erro no ciclo: {str(e)[:80]}"   # f-string CORRIGIDA
                time.sleep(2)

# ============================== INTERFACE ==============================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BYBIT SCALPING</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 8px 8px 75px 8px; }
        .container { max-width: 480px; margin: auto; }
        h1 { color: #f59e0b; text-align: center; font-size: 18px; margin: 8px 0 2px 0; }
        .clock { text-align: center; font-size: 11px; color: #38bdf8; margin-bottom: 10px; font-weight: bold; }
        .balance-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .balance-box { background: #1e293b; border: 1px solid #334155; padding: 10px; border-radius: 8px; text-align: center; }
        .balance-box span { display: block; font-size: 10px; color: #94a3b8; text-transform: uppercase; margin-bottom: 2px; }
        .balance-box strong { font-size: 14px; color: #f59e0b; }
        .card { background: #1e293b; border: 1px solid #334155; padding: 12px; border-radius: 8px; margin-bottom: 10px; }
        .card h3 { color: #38bdf8; font-size: 12px; margin-top: 0; margin-bottom: 8px; text-transform: uppercase; }
        input[type="text"], input[type="password"], input[type="number"] { width: 100%; padding: 8px; margin-top: 4px; margin-bottom: 8px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #fff; box-sizing: border-box; font-size: 14px; }
        .checkbox-container { display: flex; align-items: center; gap: 8px; margin: 8px 0; font-size: 13px; color: #cbd5e1; cursor: pointer; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #1e293b; border-top: 1px solid #334155; display: flex; justify-content: space-around; align-items: center; padding: 6px 0; z-index: 100; height: 50px; }
        .nav-btn { background: none; border: none; color: #94a3b8; font-size: 10px; font-weight: bold; cursor: pointer; text-align: center; flex: 1; }
        .nav-btn.active { color: #f59e0b; }
        .center-toggle-container { flex: 0; display: flex; justify-content: center; position: relative; bottom: 10px; }
        .btn-circle { width: 44px; height: 44px; border-radius: 50%; border: none; display: flex; align-items: center; justify-content: center; font-size: 18px; cursor: pointer; color: white; }
        .btn-circle.start { background: #16a34a; }
        .btn-circle.stop { background: #dc2626; }
        .log-box { background: #0f172a; border-left: 3px solid #f59e0b; padding: 8px; border-radius: 4px; font-size: 11px; color: #fde68a; word-break: break-all; max-height: 90px; overflow-y: auto; }
        .log-box.erro { border-left-color: #ef4444; color: #fca5a5; }
        .market-item { display: flex; justify-content: space-between; align-items: center; background: #334155; padding: 8px 10px; border-radius: 6px; margin-bottom: 6px; font-size: 13px; }
        p { margin: 6px 0; font-size: 13px; }
    </style>
    <script>
        function showTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            let b = document.getElementById('btn-' + tabId);
            if (b) b.classList.add('active');
            localStorage.setItem('activeBybitTab', tabId);
        }
        window.onload = function() {
            let saved = localStorage.getItem('activeBybitTab');
            if (saved && document.getElementById(saved)) showTab(saved);
            setInterval(function() {
                fetch('/api/state').then(r => r.json()).then(data => {
                    let logBox = document.querySelector('.log-box');
                    if (logBox && data.log) {
                        logBox.innerText = data.log;
                        logBox.classList.toggle('erro', /Erro|Falha|insuficiente/i.test(data.log));
                    }
                    let clock = document.querySelector('.clock');
                    if (clock && data.last_update) clock.innerText = "Sincronizado: " + data.last_update;
                }).catch(() => {});
            }, 2000);
        }
    </script>
</head>
<body>
    <div class="container">
        <h1>BYBIT SCALPING</h1>
        <div class="clock">Sincronizado: {{ last_update }}</div>

        <div id="dashboard" class="tab-content active">
            <div class="balance-grid">
                <div class="balance-box"><span>Inicial</span><strong>{{ "%.2f"|format(initial_balance) }}</strong></div>
                <div class="balance-box"><span>Disponível ({{ 'TESTNET' if is_demo else 'REAL' }})</span><strong>{{ "%.2f"|format(balance) }}</strong></div>
            </div>
            <div class="card">
                <h3>Posição Ativa</h3>
                {% if active_position %}
                    <p>Ativo: <b>{{ active_position.pair }}</b> — {{ active_position.side.upper() }}</p>
                    <p>Entrada: <b>{{ "%.10g"|format(active_position.entry_price) }}</b></p>
                    <p>Cume: <b>{{ "%.10g"|format(active_position.highest_price) }}</b> | Stop: <b>{{ "%.10g"|format(active_position.stop_loss) }}</b></p>
                {% else %}
                    <p style="text-align:center;color:#94a3b8;font-size:12px;">{{ 'Em Stand-by (Aguardando Sinal).' if running else 'Robô parado.' }}</p>
                {% endif %}
            </div>
            <div class="card">
                <h3>Capital & Alavancagem</h3>
                <p>Alavancagem: <b>{{ leverage }}x</b> | Poder: <b>{{ "%.2f"|format(balance * leverage) }}</b></p>
            </div>
            <div class="balance-grid">
                <div class="balance-box"><span>Status</span><strong style="color:{{ '#4ade80' if running else '#f87171' }};font-size:13px;">{{ 'OPERANDO' if running else 'PARADO' }}</strong></div>
                <div class="balance-box"><span>PNL Realizado</span><strong style="font-size:13px;color:{{ '#4ade80' if realized_pnl >= 0 else '#f87171' }}">{{ "%.4f"|format(realized_pnl) }}</strong></div>
            </div>
            <div class="card">
                <h3>Log do Sistema</h3>
                <div class="log-box {{ 'erro' if ('Erro' in log or 'Falha' in log) }}">{{ log }}</div>
            </div>
        </div>

        <div id="mercado" class="tab-content">
            <div class="card">
                <h3>Mercado em Tempo Real</h3>
                {% if market_data %}
                    {% for item in market_data %}
                    <div class="market-item"><div><b>{{ item.pair }}</b><br><span style="font-size:12px;color:#cbd5e1;">{{ "%.10g"|format(item.price) }} USDT</span></div></div>
                    {% endfor %}
                {% else %}
                    <p style="text-align:center;color:#94a3b8;font-size:12px;">Sincronize as chaves Bybit para ver dados de mercado.</p>
                {% endif %}
            </div>
        </div>

        <div id="historico" class="tab-content">
            <div class="card">
                <h3>Registo de Operações</h3>
                {% if history %}
                    {% for h in history %}
                    <div class="market-item">
                        <div><b>{{ h.pair }}</b> {{ h.side.upper() }}<br><span style="font-size:12px;color:#cbd5e1;">{{ h.time }} — {{ h.reason }}</span></div>
                        <div style="color:{{ '#4ade80' if h.pnl >= 0 else '#f87171' }};font-weight:bold;">{{ "%.4f"|format(h.pnl) }}</div>
                    </div>
                    {% endfor %}
                {% else %}
                    <p style="text-align:center;color:#94a3b8;font-size:12px;">Sem operações registadas.</p>
                {% endif %}
            </div>
        </div>

        <div id="ajustes" class="tab-content">
            <div class="card">
                <h3>Configuração Bybit API</h3>
                <form action="/settings" method="POST">
                    <label style="font-size:11px;color:#94a3b8;">API Key:</label>
                    <input type="text" name="api_key" value="{{ api_key }}">
                    <label style="font-size:11px;color:#94a3b8;">API Secret:</label>
                    <input type="password" name="api_secret" value="{{ api_secret }}">
                    <label style="font-size:11px;color:#94a3b8;">Alavancagem:</label>
                    <input type="number" name="leverage" value="{{ leverage }}" min="1" max="50" required>
                    <label class="checkbox-container">
                        <input type="checkbox" name="is_demo" {% if is_demo %}checked{% endif %}>
                        Usar Testnet (desmarque para conta REAL)
                    </label>
                    <button type="submit" style="width:100%;padding:10px;border-radius:6px;border:none;font-size:14px;font-weight:bold;cursor:pointer;background:#f59e0b;color:#0f172a;margin-top:6px;">Guardar Definições</button>
                </form>
            </div>
        </div>

        <div class="nav-bar">
            <button id="btn-dashboard" class="nav-btn active" onclick="showTab('dashboard')">📊<br>Dashboard</button>
            <button id="btn-mercado" class="nav-btn" onclick="showTab('mercado')">📈<br>Mercado</button>
            <div class="center-toggle-container">
                <form action="/toggle" method="POST" style="margin:0;">
                    <button type="submit" class="btn-circle {{ 'stop' if running else 'start' }}">{{ '⏹' if running else '▶' }}</button>
                </form>
            </div>
            <button id="btn-historico" class="nav-btn" onclick="showTab('historico')">📋<br>Histórico</button>
            <button id="btn-ajustes" class="nav-btn" onclick="showTab('ajustes')">⚙️<br>Ajustes</button>
        </div>
    </div>
</body>
</html>
"""

# ============================== BACKGROUND ==============================
def fetch_data():
    ex = get_exchange()
    if not ex:
        return
    try:
        total = get_usdt_balance(ex)
        if total > 0:
            if bot_state["initial_balance"] == 0.0:
                bot_state["initial_balance"] = total
            bot_state["balance"] = total

        m_list = []
        for sym in PAIRS:
            try:
                t = ex.fetch_ticker(sym)
                m_list.append({"pair": sym.split('/')[0], "price": t.get('last') or 0.0})
            except Exception:
                continue
        bot_state["market_data"] = m_list
        bot_state["last_update"] = datetime.datetime.now().strftime("%H:%M:%S")
    except Exception:
        pass

def background_loop():
    while True:
        try:
            fetch_data()   # atualiza mesmo parado, para o relógio/saldo funcionarem
        except Exception:
            pass
        time.sleep(3)

# ============================== ROTAS ==============================
@app.route('/api/state')
def api_state():
    return jsonify({"log": str(bot_state["log"]), "last_update": str(bot_state["last_update"])})

@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        running=bot_state["running"],
        initial_balance=float(bot_state["initial_balance"]),
        balance=float(bot_state["balance"]),
        realized_pnl=float(bot_state["realized_pnl"]),
        active_position=bot_state["active_position"],
        market_data=bot_state["market_data"],
        history=bot_state["history"],
        api_key=str(bot_state["api_key"]),
        api_secret=str(bot_state["api_secret"]),
        leverage=int(bot_state["leverage"]),
        is_demo=bool(bot_state["is_demo"]),
        last_update=str(bot_state["last_update"]),
        log=str(bot_state["log"])
    )

@app.route('/settings', methods=['POST'])
def settings():
    global global_exchange, engine, engine_thread
    global_exchange = None
    engine = None
    engine_thread = None
    bot_state["running"] = False
    bot_state["active_position"] = None

    bot_state["api_key"] = str(request.form.get("api_key", "")).strip()
    bot_state["api_secret"] = str(request.form.get("api_secret", "")).strip()
    bot_state["is_demo"] = True if request.form.get("is_demo") else False
    try:
        bot_state["leverage"] = int(request.form.get("leverage", 21))
    except (TypeError, ValueError):
        bot_state["leverage"] = 21
    bot_state["log"] = "Definições guardadas. A ligar..."
    return redirect(url_for('index'))

@app.route('/toggle', methods=['POST'])
def toggle():
    global global_exchange, engine, engine_thread

    if not bot_state["running"]:
        if not bot_state["api_key"] or not bot_state["api_secret"]:
            bot_state["log"] = "Erro: insira as chaves Bybit em Ajustes!"
            return redirect(url_for('index'))

        ex = get_exchange()
        if not ex:
            return redirect(url_for('index'))  # log de erro já definido em get_exchange()

        bot_state["running"] = True
        engine = ScalpingEngine(ex, PAIRS, bot_state["leverage"])
        engine_thread = threading.Thread(target=engine.execute_scalp_loop,
                                         args=(bot_state,), daemon=True)
        engine_thread.start()
        bot_state["log"] = f"Robô ativado ({'TESTNET' if bot_state['is_demo'] else 'REAL'})."
    else:
        bot_state["running"] = False
        engine = None
        bot_state["active_position"] = None
        bot_state["log"] = "Robô parado."
    return redirect(url_for('index'))

if __name__ == '__main__':
    threading.Thread(target=background_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
