# -*- coding: utf-8 -*-
"""
ND-SCALPING — painel web (Flask) + robô de scalping Bybit.

Render (Web Service):
  Build Command:  pip install -r requirements.txt
  Start Command:  gunicorn app:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT
  Nenhuma variável de ambiente é necessária: a palavra-passe do painel e as chaves da Bybit
  são inseridas no próprio painel (1.º acesso e separador Ajustes).
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import timedelta
from functools import wraps

from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for

import config as C
from exchange_management import MODES, test_connection
from trading import push_log, supervisor

app = Flask(__name__)

app.secret_key = os.urandom(32).hex()     # novo a cada arranque: depois de reiniciar, é preciso entrar de novo
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.getenv("RENDER")),   # a Render serve em https
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

# Estado partilhado entre o painel (Flask) e o robô (thread própria).
bot_state = {
    "running": False,
    "reconnect": False,
    "api_key": "",
    "api_secret": "",
    "mode": C.MODE_DEFAULT if C.MODE_DEFAULT in MODES else "testnet",
    "leverage": int(C.LEVERAGE_DEFAULT),
    "margin_usdt": float(C.MARGIN_DEFAULT_USDT),
    "initial_balance": 0.0,
    "balance": 0.0,
    "free": 0.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "market_data": [],
    "scan_info": "",
    "history": [],
    "events": [],
    "last_update": "Aguardando...",
    "log": "ND-SCALPING parado.",
}


# ============================ ARMAZENAMENTO E SEGURANÇA ============================
# A palavra-passe do painel é criada no 1.º acesso (nada na Render). Fica guardada como hash e é
# ela que cifra as chaves da Bybit guardadas em disco. O segredo nunca é mostrado de volta.
ITER = 200_000
_lock = threading.RLock()
_store = {}        # conteúdo de settings.json
_fernet = None     # chave de cifra: só existe em memória, depois de entrares com a palavra-passe


def _data_dir():
    for d in (os.getenv("DATA_DIR"), "/var/data"):            # /var/data = Disk permanente da Render
        if d and os.path.isdir(d) and os.access(d, os.W_OK):
            return d, True
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")   # temporário
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d, False


DATA_DIR, PERSISTENT = _data_dir()
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def _load():
    global _store
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            _store = json.load(f)
    except (OSError, ValueError):
        _store = {}


def _save():
    with _lock:
        try:
            tmp = SETTINGS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_store, f)
            os.replace(tmp, SETTINGS_FILE)
            try:
                os.chmod(SETTINGS_FILE, 0o600)
            except OSError:
                pass
            return True
        except OSError:
            return False


def _pw_hash(pw, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), ITER).hex()


def _make_fernet(pw, salt_hex):
    key = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), ITER, dklen=32)
    return Fernet(base64.urlsafe_b64encode(key))


def has_password():
    return bool(_store.get("pw_hash"))


def check_password(pw):
    return has_password() and hmac.compare_digest(_pw_hash(pw, _store["pw_salt"]), _store["pw_hash"])


def store_credentials():
    """Cifra as chaves que estão em memória e guarda-as em disco. Devolve False se não for possível."""
    if _fernet is None:
        return False
    if bot_state["api_key"] and bot_state["api_secret"]:
        payload = json.dumps({"k": bot_state["api_key"], "s": bot_state["api_secret"]}).encode()
        _store["creds"] = _fernet.encrypt(payload).decode()
    else:
        _store.pop("creds", None)
    return True


def persist():
    """Guarda em disco as preferências (ambiente, alavancagem, margem) e as chaves cifradas."""
    _store.update(mode=bot_state["mode"], leverage=bot_state["leverage"], margin_usdt=bot_state["margin_usdt"])
    return _save()


def set_password(pw):
    """Define (ou altera) a palavra-passe do painel e volta a cifrar as chaves com ela."""
    global _fernet
    with _lock:
        _store["pw_salt"] = secrets.token_hex(16)
        _store["pw_hash"] = _pw_hash(pw, _store["pw_salt"])
        _store["enc_salt"] = secrets.token_hex(16)
        _fernet = _make_fernet(pw, _store["enc_salt"])
        store_credentials()
        _save()


def unlock(pw):
    """Chamado depois de entrares: ativa a cifra e carrega as chaves guardadas para a memória."""
    global _fernet
    _fernet = _make_fernet(pw, _store["enc_salt"])
    if bot_state["api_key"] and bot_state["api_secret"]:
        return
    token = _store.get("creds")
    if not token:
        return
    try:
        c = json.loads(_fernet.decrypt(token.encode()).decode())
        bot_state["api_key"], bot_state["api_secret"] = c["k"], c["s"]
        push_log(bot_state, "Chaves da Bybit carregadas. Carrega em INICIAR ROBÔ.")
    except (InvalidToken, ValueError, KeyError):
        push_log(bot_state, "Não consegui ler as chaves guardadas. Insere-as de novo em Ajustes.")


def _apply_prefs():
    if _store.get("mode") in MODES:
        bot_state["mode"] = _store["mode"]
    try:
        bot_state["leverage"] = max(1, min(50, int(_store.get("leverage", bot_state["leverage"]))))
        bot_state["margin_usdt"] = max(1.0, float(_store.get("margin_usdt", bot_state["margin_usdt"])))
    except (TypeError, ValueError):
        pass


_load()
_apply_prefs()

_fails = {}


def _ip():
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?"


def _locked(ip):
    n, t = _fails.get(ip, (0, 0.0))
    if time.time() - t >= 600:
        _fails.pop(ip, None)
        return False
    return n >= 5


def _fail(ip):
    n, _ = _fails.get(ip, (0, 0.0))
    _fails[ip] = (n + 1, time.time())


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not has_password() or not session.get("ok"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "login"}), 401
            return redirect(url_for("login" if has_password() else "setup"))
        return fn(*a, **kw)
    return wrapper


_PAGE_CSS = """body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b0f19;color:#f8fafc;margin:0;padding:24px}
.box{max-width:360px;margin:70px auto;background:#131b2e;border:1px solid #1e293b;border-radius:8px;padding:20px}
h1{color:#22c55e;text-align:center;font-size:16px;letter-spacing:1.5px;margin-top:0}
p{font-size:13px;color:#cbd5e1;line-height:1.5}
input{width:100%;padding:12px;margin:8px 0;border-radius:6px;border:1px solid #1e293b;background:#0b0f19;color:#fff;box-sizing:border-box;font-size:14px}
button{width:100%;padding:13px;border:none;border-radius:8px;background:#22c55e;color:#fff;font-weight:800;letter-spacing:1px;font-size:13px;margin-top:6px}
.err{color:#f87171;font-size:12px;margin:6px 0}"""

LOGIN_HTML = """<!DOCTYPE html><html lang="pt"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ND-SCALPING</title>
<style>""" + _PAGE_CSS + """</style></head>
<body><div class="box"><h1>ND-SCALPING</h1>
<form method="POST"><input type="password" name="password" placeholder="Palavra-passe do painel" autofocus required>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<button type="submit">ENTRAR</button></form></div></body></html>"""

SETUP_HTML = """<!DOCTYPE html><html lang="pt"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ND-SCALPING</title>
<style>""" + _PAGE_CSS + """</style></head>
<body><div class="box"><h1>ND-SCALPING</h1>
<p><b>Primeiro acesso.</b> Cria a palavra-passe do painel. Ela protege o painel e cifra as chaves da Bybit que guardares em Ajustes.</p>
<form method="POST">
<input type="password" name="password" placeholder="Palavra-passe (mínimo 8 caracteres)" minlength="8" autofocus required>
<input type="password" name="password2" placeholder="Repetir palavra-passe" minlength="8" required>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<button type="submit">CRIAR E ENTRAR</button></form></div></body></html>"""


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if has_password():
        return redirect(url_for("login"))
    error = None
    if request.method == "POST":
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        if len(pw) < 8:
            error = "A palavra-passe precisa de pelo menos 8 caracteres."
        elif pw != pw2:
            error = "As palavras-passe não coincidem."
        else:
            with _lock:
                if has_password():
                    return redirect(url_for("login"))
                set_password(pw)
            session.clear()
            session["ok"] = True
            session.permanent = True
            push_log(bot_state, "Palavra-passe criada. Insere as chaves da Bybit em Ajustes.")
            return redirect(url_for("index"))
    return render_template_string(SETUP_HTML, error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if not has_password():
        return redirect(url_for("setup"))
    error = None
    if request.method == "POST":
        ip = _ip()
        pw = request.form.get("password", "")
        if _locked(ip):
            error = "Demasiadas tentativas. Tenta daqui a 10 minutos."
        elif check_password(pw):
            _fails.pop(ip, None)
            session.clear()
            session["ok"] = True
            session.permanent = True
            unlock(pw)
            return redirect(url_for("index"))
        else:
            _fail(ip)
            error = "Palavra-passe incorreta."
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/password", methods=["POST"])
@login_required
def password():
    f, ip = request.form, _ip()
    cur, new, new2 = f.get("current", ""), f.get("new", ""), f.get("new2", "")
    if _locked(ip):
        msg = "Demasiadas tentativas. Tenta daqui a 10 minutos."
    elif not check_password(cur):
        _fail(ip)
        msg = "✖ Palavra-passe atual incorreta."
    elif len(new) < 8:
        msg = "✖ A nova palavra-passe precisa de pelo menos 8 caracteres."
    elif new != new2:
        msg = "✖ As novas palavras-passe não coincidem."
    else:
        set_password(new)
        msg = "✔ Palavra-passe do painel alterada."
    push_log(bot_state, msg)
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return "ok"          # público e sem dados: serve para pings (UptimeRobot) e health check da Render


# ============================ PAINEL ============================
def mask(s):
    s = str(s or "")
    if not s:
        return ""
    return s[:4] + "…" + s[-4:] if len(s) > 8 else "••••"


def snapshot():
    s = bot_state
    return {
        "running": s["running"],
        "mode": s["mode"],
        "mode_label": MODES.get(s["mode"], s["mode"]),
        "leverage": s["leverage"],
        "margin_usdt": s["margin_usdt"],
        "balance": s["balance"],
        "initial_balance": s["initial_balance"],
        "free": s["free"],
        "realized_pnl": s["realized_pnl"],
        "active_position": s["active_position"],
        "market_data": list(s["market_data"]),
        "scan_info": s["scan_info"],
        "history": list(s["history"])[:30],
        "events": list(s["events"])[:8],
        "last_update": s["last_update"],
        "log": s["log"],
    }


@app.route("/api/state")
@login_required
def api_state():
    return jsonify(snapshot())


@app.route("/")
@login_required
def index():
    s = bot_state
    return render_template_string(
        HTML_TEMPLATE,
        modes=MODES,
        mode=s["mode"],
        leverage=int(s["leverage"]),
        margin=float(s["margin_usdt"]),
        key_mask=mask(s["api_key"]),
        secret_set=bool(s["api_secret"]),
        running=s["running"],
        total_pairs=len(C.PAIRS),
        persistent=PERSISTENT,
    )


@app.route("/settings", methods=["POST"])
@login_required
def settings():
    f = request.form
    s = bot_state
    key = (f.get("api_key") or "").strip()
    secret = (f.get("api_secret") or "").strip()
    mode = f.get("mode", s["mode"])
    if mode not in MODES:
        mode = s["mode"]

    changed = False
    if key and key != s["api_key"]:
        s["api_key"], changed = key, True
    if secret and secret != s["api_secret"]:
        s["api_secret"], changed = secret, True
    if mode != s["mode"]:
        s["mode"], changed = mode, True
    try:
        s["leverage"] = max(1, min(50, int(f.get("leverage", s["leverage"]))))
    except (TypeError, ValueError):
        pass
    try:
        s["margin_usdt"] = max(1.0, float(str(f.get("margin_usdt", s["margin_usdt"])).replace(",", ".")))
    except (TypeError, ValueError):
        pass

    saved = store_credentials()
    persist()
    msg = "Definições guardadas." if saved else "Definições guardadas só em memória (entra de novo no painel para as cifrar em disco)."
    if changed:
        s["initial_balance"], s["realized_pnl"], s["history"] = 0.0, 0.0, []
        if s["running"]:
            s["reconnect"] = True
            msg += " A reconectar com as novas chaves (a posição aberta é fechada)."

    if f.get("action") == "test":
        ok, res = asyncio.run(test_connection(dict(s)))
        msg = ("✔ " if ok else "✖ ") + res
    push_log(s, msg)
    return redirect(url_for("index"))


@app.route("/toggle", methods=["POST"])
@login_required
def toggle():
    s = bot_state
    if not s["running"]:
        if not s["api_key"] or not s["api_secret"]:
            push_log(s, "Erro: insere as chaves Bybit em Ajustes!")
            return redirect(url_for("index"))
        s["running"] = True
        push_log(s, "A iniciar o robô...")
    else:
        s["running"] = False
        push_log(s, "A parar... a posição aberta (se existir) é fechada.")
    return redirect(url_for("index"))


# ============================ ROBÔ (thread própria) ============================
def _bot_thread():
    while True:
        try:
            asyncio.run(supervisor(bot_state))
        except Exception as e:                           # nunca deixa o robô morrer em silêncio
            bot_state["running"] = False
            push_log(bot_state, f"Erro interno: {str(e)[:100]}")
            time.sleep(5)


def start_background():
    if getattr(app, "_bot_started", False):
        return
    app._bot_started = True
    threading.Thread(target=_bot_thread, name="nd-bot", daemon=True).start()


start_background()


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ND-SCALPING</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding: 12px 12px 80px 12px; }
        .container { max-width: 480px; margin: auto; }
        h1 { color: #22c55e; text-align: center; font-size: 16px; margin: 4px 0 2px 0; font-weight: 800; letter-spacing: 1.5px; }
        .clock { text-align: center; font-size: 11px; color: #38bdf8; margin-bottom: 12px; font-weight: bold; }
        .balance-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .balance-box { background: #131b2e; border: 1px solid #1e293b; padding: 12px 8px; border-radius: 8px; text-align: center; }
        .balance-box span { display: block; font-size: 9px; color: #64748b; text-transform: uppercase; margin-bottom: 4px; font-weight: 700; }
        .balance-box strong { font-size: 14px; color: #22c55e; }
        .card { background: #131b2e; border: 1px solid #1e293b; padding: 14px; border-radius: 8px; margin-bottom: 10px; }
        .card h3 { color: #38bdf8; font-size: 11px; margin-top: 0; margin-bottom: 10px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px; }
        label { font-size: 12px; color: #38bdf8; font-weight: 600; display: block; margin-top: 8px; }
        input[type="text"], input[type="number"], input[type="password"], select { width: 100%; padding: 10px; margin-top: 6px; margin-bottom: 10px; border-radius: 6px; border: 1px solid #1e293b; background: #0b0f19; color: #fff; box-sizing: border-box; font-size: 13px; }
        .btn-action { width: 100%; padding: 14px; border-radius: 8px; border: none; font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; cursor: pointer; color: #ffffff; }
        .btn-action.start { background: #22c55e; }
        .btn-action.stop { background: #ef4444; }
        .btn-save { width: 100%; padding: 12px; border-radius: 6px; border: none; font-size: 13px; font-weight: bold; cursor: pointer; background: #0284c7; color: #ffffff; margin-top: 6px; }
        .btn-test { background: #334155; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #0b0f19; border-top: 1px solid #1e293b; display: flex; justify-content: space-around; align-items: center; padding: 8px 0; z-index: 100; height: 52px; }
        .nav-btn { background: none; border: none; color: #64748b; font-size: 10px; font-weight: bold; cursor: pointer; text-align: center; flex: 1; }
        .nav-btn.active { color: #22c55e; }
        .log-box { background: #0b0f19; border-left: 3px solid #22c55e; padding: 10px; border-radius: 4px; font-size: 12px; color: #22c55e; font-weight: 600; word-break: break-word; }
        .events { margin-top: 8px; font-size: 10px; color: #64748b; line-height: 1.5; word-break: break-word; }
        .market-item { display: flex; justify-content: space-between; align-items: center; background: #0b0f19; padding: 10px 12px; border-radius: 6px; margin-bottom: 8px; border: 1px solid #1e293b; }
        .badge-neutral, .badge-long, .badge-short { font-size: 10px; padding: 3px 8px; border-radius: 4px; font-weight: bold; white-space: nowrap; }
        .badge-neutral { background: #1e293b; color: #94a3b8; }
        .badge-long { background: #14532d; color: #4ade80; }
        .badge-short { background: #7f1d1d; color: #f87171; }
        .sub { font-size: 11px; color: #94a3b8; }
        .muted { text-align: center; color: #94a3b8; font-size: 12px; margin: 14px 0; }
        .pos { color: #22c55e; } .neg { color: #ef4444; }
        .mode-tag { display: inline-block; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; background: #1e293b; color: #38bdf8; }
        .mode-tag.real { background: #7f1d1d; color: #fecaca; }
        p { margin: 4px 0; font-size: 13px; }
        .hint { font-size: 11px; color: #64748b; margin: -4px 0 8px 0; }
        a.logout { display: block; text-align: center; color: #64748b; font-size: 12px; margin-top: 14px; }
    </style>
    <script>
        function showTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(function (el) { el.classList.remove('active'); });
            document.querySelectorAll('.nav-btn').forEach(function (el) { el.classList.remove('active'); });
            document.getElementById(tabId).classList.add('active');
            var b = document.getElementById('btn-' + tabId);
            if (b) { b.classList.add('active'); }
            localStorage.setItem('activeNdTab', tabId);
        }
        function esc(s) {
            return String(s).replace(/[&<>"']/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
            });
        }
        function money(x) { return Number(x || 0).toFixed(2); }
        function sgn(x, d) { x = Number(x || 0); return (x >= 0 ? '+' : '') + x.toFixed(d); }
        function setText(id, t) { var e = document.getElementById(id); if (e) { e.innerText = t; } }

        function render(d) {
            setText('clock', 'Sincronizado: ' + d.last_update);
            setText('bal-initial', money(d.initial_balance));
            setText('bal-now', money(d.balance));
            setText('lev-title', 'ALAVANCAGEM CONFIGURADA: ' + d.leverage + 'x');
            setText('lev-info', 'Margem por operação: ' + money(d.margin_usdt) + ' USDT → posição de ' + money(d.margin_usdt * d.leverage) + ' USDT');
            setText('free', 'Saldo livre: ' + money(d.free) + ' USDT');
            var st = document.getElementById('status');
            st.innerText = d.running ? 'OPERANDO' : 'PARADO';
            st.style.color = d.running ? '#22c55e' : '#ef4444';
            var pn = document.getElementById('pnl');
            pn.innerText = sgn(d.realized_pnl, 4);
            pn.style.color = d.realized_pnl >= 0 ? '#22c55e' : '#ef4444';
            var mt = document.getElementById('mode-tag');
            mt.innerText = d.mode_label;
            mt.className = 'mode-tag' + (d.mode === 'real' ? ' real' : '');
            setText('log-box', d.log);
            setText('events', d.events.join('\\n'));
            var btn = document.getElementById('toggle-btn');
            btn.className = 'btn-action ' + (d.running ? 'stop' : 'start');
            btn.innerText = d.running ? 'PARAR ROBÔ' : 'INICIAR ROBÔ';

            var p = d.active_position, pb = document.getElementById('pos-box');
            if (p) {
                var cls = p.pnl_pct >= 0 ? 'pos' : 'neg';
                pb.innerHTML = '<b>' + esc(p.side) + ' ' + esc(p.pair) + '</b>' + (p.trailing ? ' <span class="badge-long">DINAMITE</span>' : '') +
                    '<p class="sub">Entrada ' + esc(p.entry) + ' | Preço ' + esc(p.price) + '</p>' +
                    '<p class="' + cls + '" style="font-size:16px;font-weight:800">' + sgn(p.pnl_pct, 3) + '%</p>' +
                    '<p class="sub">SL ' + esc(p.sl) + ' | TP ' + esc(p.tp) + '</p>';
            } else {
                pb.innerHTML = '<p class="muted">Nenhuma posição ativa no momento.</p>';
            }

            setText('scan-info', d.scan_info ? ('Varredura: ' + d.scan_info) : '');
            var ml = document.getElementById('market-list');
            if (!d.market_data.length) {
                ml.innerHTML = '<p class="muted">' + (d.running ? 'A carregar cotações...' : 'Inicia o robô para ver o mercado.') + '</p>';
            } else {
                var h = '';
                d.market_data.forEach(function (it) {
                    var c = it.status === 'LONG' ? 'badge-long' : (it.status === 'SHORT' ? 'badge-short' : 'badge-neutral');
                    h += '<div class="market-item"><div><b style="font-size:14px">' + esc(it.pair) + '</b><br><span class="sub">Preço: ' + esc(it.price) +
                        ' | 1m: ' + esc(it.move) + '% | Vol: ' + esc(it.vr) + 'x</span></div><span class="' + c + '">' + esc(it.status) + '</span></div>';
                });
                ml.innerHTML = h;
            }

            var hl = document.getElementById('history-list');
            if (!d.history.length) {
                hl.innerHTML = '<p class="muted">Nenhuma operação fechada ainda.</p>';
            } else {
                var x = '';
                d.history.forEach(function (t) {
                    var c = t.pnl >= 0 ? 'pos' : 'neg';
                    x += '<div class="market-item"><div><b>' + esc(t.side) + ' ' + esc(t.pair) + '</b><br><span class="sub">' + esc(t.time) + ' | ' +
                        esc(t.entry) + ' → ' + esc(t.exit) + '<br>' + esc(t.reason) + '</span></div><b class="' + c + '">' + sgn(t.pnl, 4) + '</b></div>';
                });
                hl.innerHTML = x;
            }
        }

        function refresh() {
            fetch('/api/state', { credentials: 'same-origin' })
                .then(function (r) { if (r.status === 401) { location.reload(); return null; } return r.json(); })
                .then(function (d) { if (d) { render(d); } })
                .catch(function () {});
        }

        window.onload = function () {
            var saved = localStorage.getItem('activeNdTab');
            if (saved && document.getElementById(saved)) { showTab(saved); }
            refresh();
            setInterval(refresh, 2000);
        };
    </script>
</head>
<body>
    <div class="container">
        <h1>ND-SCALPING</h1>
        <div class="clock" id="clock">Sincronizado: ...</div>

        <div id="dashboard" class="tab-content active">
            <div class="balance-grid">
                <div class="balance-box"><span>INICIAL (USDT)</span><strong id="bal-initial">0.00</strong></div>
                <div class="balance-box"><span>ATUAL (USDT)</span><strong id="bal-now">0.00</strong></div>
            </div>

            <div class="card" id="pos-box"><p class="muted">Nenhuma posição ativa no momento.</p></div>

            <div class="card">
                <h3 id="lev-title">ALAVANCAGEM CONFIGURADA: {{ leverage }}x</h3>
                <p class="sub" id="lev-info"></p>
                <p class="sub" id="free"></p>
                <p style="margin-top:8px"><span class="mode-tag" id="mode-tag">{{ modes[mode] }}</span></p>
            </div>

            <div class="balance-grid">
                <div class="balance-box"><span>STATUS</span><strong id="status" style="font-size: 12px; color: #ef4444;">PARADO</strong></div>
                <div class="balance-box"><span>PNL REALIZADO</span><strong id="pnl" style="font-size: 12px;">+0.0000</strong></div>
            </div>

            <div class="card">
                <h3>ESTADO / LOG DA API:</h3>
                <div class="log-box" id="log-box">...</div>
                <div class="events" id="events" style="white-space: pre-line;"></div>
            </div>

            <form action="/toggle" method="POST" style="margin-top: 15px;">
                <button type="submit" id="toggle-btn" class="btn-action {{ 'stop' if running else 'start' }}">{{ 'PARAR ROBÔ' if running else 'INICIAR ROBÔ' }}</button>
            </form>
            <p class="hint" style="text-align:center;margin-top:8px">Ao parar, a posição aberta é fechada a mercado.</p>
        </div>

        <div id="mercado" class="tab-content">
            <div class="card">
                <h3>MERCADO SCALPING ({{ total_pairs }} PARES &lt; 1 USDT)</h3>
                <p class="sub" id="scan-info" style="margin-bottom:8px"></p>
                <div id="market-list"><p class="muted">A carregar cotações...</p></div>
            </div>
        </div>

        <div id="historico" class="tab-content">
            <div class="card">
                <h3>REGISTO DE TRADES</h3>
                <div id="history-list"><p class="muted">Nenhuma operação fechada ainda.</p></div>
            </div>
        </div>

        <div id="ajustes" class="tab-content">
            <div class="card">
                <h3 style="margin-bottom: 15px;">Configuração &amp; Alavancagem</h3>
                <form action="/settings" method="POST" autocomplete="off">
                    <label>Ambiente da chave:</label>
                    <select name="mode">
                        {% for k, v in modes.items() %}<option value="{{ k }}" {% if k == mode %}selected{% endif %}>{{ v }}</option>{% endfor %}
                    </select>
                    <p class="hint">A chave tem de ser criada no mesmo ambiente escolhido aqui.</p>

                    <label>Bybit API Key:</label>
                    <input type="text" name="api_key" value="" placeholder="{{ key_mask if key_mask else 'cola a API Key' }}" autocapitalize="off" autocorrect="off" spellcheck="false">

                    <label>Bybit API Secret:</label>
                    <input type="password" name="api_secret" value="" placeholder="{{ 'guardado ✔ (deixa vazio para manter)' if secret_set else 'cola o API Secret' }}">

                    <label>Alavancagem Manual:</label>
                    <input type="number" name="leverage" value="{{ leverage }}" min="1" max="50" required>

                    <label>Margem por operação (USDT):</label>
                    <input type="number" name="margin_usdt" value="{{ margin }}" min="1" step="0.5" required>

                    <button type="submit" name="action" value="save" class="btn-save">Guardar Definições</button>
                    <button type="submit" name="action" value="test" class="btn-save btn-test">Guardar e testar ligação à Bybit</button>
                </form>
                <p class="hint" style="margin-top:10px">O secret nunca é mostrado de volta.
                {% if persistent %}As chaves ficam guardadas no servidor, cifradas com a palavra-passe do painel.
                {% else %}<span style="color:#f59e0b">Armazenamento temporário: se a Render reiniciar, a palavra-passe e as chaves perdem-se e tens de as inserir de novo. Para guardar de forma permanente, adiciona um Disk na Render com Mount Path /var/data.</span>{% endif %}</p>
            </div>

            <div class="card">
                <h3 style="margin-bottom: 15px;">Segurança do painel</h3>
                <form action="/password" method="POST" autocomplete="off">
                    <label>Palavra-passe atual:</label>
                    <input type="password" name="current" required>
                    <label>Nova palavra-passe (mínimo 8):</label>
                    <input type="password" name="new" minlength="8" required>
                    <label>Repetir nova palavra-passe:</label>
                    <input type="password" name="new2" minlength="8" required>
                    <button type="submit" class="btn-save">Alterar palavra-passe do painel</button>
                </form>
            </div>
            <a class="logout" href="/logout">Sair do painel</a>
        </div>

        <div class="nav-bar">
            <button id="btn-dashboard" class="nav-btn active" onclick="showTab('dashboard')">📊<br>Dashboard</button>
            <button id="btn-mercado" class="nav-btn" onclick="showTab('mercado')">📈<br>Mercado</button>
            <button id="btn-historico" class="nav-btn" onclick="showTab('historico')">📋<br>Histórico</button>
            <button id="btn-ajustes" class="nav-btn" onclick="showTab('ajustes')">⚙️<br>Ajustes</button>
        </div>
    </div>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
