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
from exchange_management import MODES, diagnose
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
    "retry": False,
    "equity": None,
    "avail": None,
    "gen": 0,                      # geração do motor (o vigia pode substituir um motor preso)
    "heartbeat": 0.0,
    "conn_step": "",
    "conn_since": 0.0,
    "diag": [],
    "diag_running": False,
    "conn": "sem_chaves",          # sem_chaves | a_ligar | ligado | erro
    "conn_msg": "",
    "initial_balance": 0.0,
    "balance": 0.0,
    "free": 0.0,
    "realized_pnl": 0.0,
    "active_position": None,
    "chart": None,
    "market_data": [],
    "market_counts": {},
    "scan_info": "",
    "history": [],
    "history_cb": None,
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
        ensure_bot()
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
.err{color:#f87171;font-size:12px;margin:6px 0}
.warn{color:#f59e0b;font-size:12px;line-height:1.5;margin:10px 0 0 0}"""

LOGIN_HTML = """<!DOCTYPE html><html lang="pt"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ND-SCALPING</title>
<style>""" + _PAGE_CSS + """</style></head>
<body><div class="box"><h1>ND-SCALPING</h1>
<form method="POST"><input type="password" name="password" placeholder="Palavra-passe do painel" autofocus required>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<button type="submit">ENTRAR</button></form>{% if not persistent %}<p class="warn">Armazenamento temporário: sempre que a Render reiniciar, a palavra-passe e as chaves apagam-se e tens de as criar de novo. Para não repetir, adiciona um Disk na Render com Mount Path /var/data.</p>{% endif %}</div></body></html>"""

SETUP_HTML = """<!DOCTYPE html><html lang="pt"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ND-SCALPING</title>
<style>""" + _PAGE_CSS + """</style></head>
<body><div class="box"><h1>ND-SCALPING</h1>
<p><b>Primeiro acesso.</b> Cria a palavra-passe do painel. Ela protege o painel e cifra as chaves da Bybit que guardares em Ajustes.</p>
<form method="POST">
<input type="password" name="password" placeholder="Palavra-passe (mínimo 8 caracteres)" minlength="8" autofocus required>
<input type="password" name="password2" placeholder="Repetir palavra-passe" minlength="8" required>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<button type="submit">CRIAR E ENTRAR</button></form>{% if not persistent %}<p class="warn">Armazenamento temporário: sempre que a Render reiniciar, a palavra-passe e as chaves apagam-se e tens de as criar de novo. Para não repetir, adiciona um Disk na Render com Mount Path /var/data.</p>{% endif %}</div></body></html>"""


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
    return render_template_string(SETUP_HTML, error=error, persistent=PERSISTENT)


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
    return render_template_string(LOGIN_HTML, error=error, persistent=PERSISTENT)


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
    ensure_bot()
    return "ok"          # público e sem dados: serve para pings (UptimeRobot) e health check da Render


# ============================ HISTÓRICO (guardado em disco) ============================
HISTORY_FILE = os.path.join(DATA_DIR, "trades.json")


def _load_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            h = json.load(f)
        return h if isinstance(h, list) else []
    except (OSError, ValueError):
        return []


def _save_history(hist):
    try:
        tmp = HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(hist)[:C.HISTORY_MAX], f)
        os.replace(tmp, HISTORY_FILE)
    except OSError:
        pass


bot_state["history"] = _load_history()
bot_state["history_cb"] = _save_history


def history_stats(h):
    def agg(rows):
        return {"n": len(rows),
                "usdt": round(sum(r.get("pnl", 0) for r in rows), 4),
                "pct": round(sum(r.get("pnl_pct", 0) for r in rows), 2)}
    wins = [r for r in h if r.get("pnl", 0) > 0]
    losses = [r for r in h if r.get("pnl", 0) < 0]
    total = agg(h)
    total["winrate"] = round(len(wins) / len(h) * 100, 1) if h else 0.0
    return {"wins": agg(wins), "losses": agg(losses), "total": total}


# ============================ PAINEL ============================
def mask(s):
    s = str(s or "")
    if not s:
        return ""
    return s[:4] + "…" + s[-4:] if len(s) > 8 else "••••"


def snapshot(tab=""):
    s = bot_state
    free = float(s["free"] or 0)
    lev = int(s["leverage"])
    ratio = 1.0 / max(1, lev) + C.FEE_RESERVE_PCT / 100
    notional = max(0.0, min(float(s["margin_usdt"]) * lev, free * C.BALANCE_USE_PCT / 100 / ratio)) if free > 0 else 0.0
    margin_eff = notional / max(1, lev)
    d = {
        "running": s["running"],
        "conn": s["conn"],
        "conn_msg": s["conn_msg"],
        "mode": s["mode"],
        "mode_label": MODES.get(s["mode"], s["mode"]),
        "leverage": lev,
        "margin_usdt": s["margin_usdt"],
        "margin_eff": round(margin_eff, 4),
        "notional": round(notional, 2),
        "min_notional": C.MIN_NOTIONAL_FALLBACK,
        "min_balance": round(C.MIN_NOTIONAL_FALLBACK * ratio / (C.BALANCE_USE_PCT / 100), 3),
        "equity": s["equity"],
        "avail": s["avail"],
        "balance": s["balance"],
        "initial_balance": s["initial_balance"],
        "free": s["free"],
        "realized_pnl": s["realized_pnl"],
        "active_position": s["active_position"],
        "scan_info": s["scan_info"],
        "events": list(s["events"])[:8],
        "last_update": s["last_update"],
        "log": s["log"],
        "motor_ok": time.time() - s["heartbeat"] < 8,
        "conn_step": s["conn_step"],
        "conn_secs": int(time.time() - s["conn_since"]) if s["conn"] == "a_ligar" and s["conn_since"] else 0,
        "diag": list(s["diag"]),
        "diag_running": s["diag_running"],
    }
    if tab == "mercado":
        d["market_data"] = list(s["market_data"])
        d["market_counts"] = dict(s["market_counts"])
    if tab == "dashboard" and s["chart"]:
        ch = dict(s["chart"])
        ch["points"] = list(ch["points"])
        d["chart"] = ch
    return d


@app.route("/api/state")
@login_required
def api_state():
    return jsonify(snapshot(request.args.get("tab", "")))


@app.route("/api/history")
@login_required
def api_history():
    h = list(bot_state["history"])
    return jsonify({"stats": history_stats(h), "trades": h[:100]})


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
        s["margin_usdt"] = max(0.1, float(str(f.get("margin_usdt", s["margin_usdt"])).replace(",", ".")))
    except (TypeError, ValueError):
        pass

    saved = store_credentials()
    persist()
    msg = "Definições guardadas." if saved else "Definições guardadas só em memória (entra de novo no painel para as cifrar em disco)."
    if changed:
        s["initial_balance"], s["realized_pnl"], s["history"] = 0.0, 0.0, []
        _save_history([])
        s["reconnect"] = True                          # liga (ou volta a ligar) à Bybit com as novas chaves
        s["conn"], s["conn_msg"] = "a_ligar", ""
        msg += " A ligar à Bybit..."
    s["retry"] = True

    if f.get("action") == "test":
        start_diag()
        msg += " A testar a ligação (resultado no Dashboard)..."
    push_log(s, msg)
    return redirect(url_for("index"))


@app.route("/diag", methods=["POST"])
@login_required
def diag():
    if start_diag():
        push_log(bot_state, "A diagnosticar a ligação à Bybit...")
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
        s["retry"] = True
        push_log(s, "Robô ativado: a procurar entradas." if s["conn"] == "ligado" else "Robô ativado: a ligar à Bybit...")
    else:
        s["running"] = False
        push_log(s, "Robô parado. A posição aberta (se existir) é fechada.")
    return redirect(url_for("index"))


# ============================ ROBÔ (thread própria) ============================
_bot = {"thread": None, "pid": None}
_bot_lock = threading.Lock()


def _bot_thread(gen):
    while bot_state.get("gen") == gen:
        try:
            asyncio.run(supervisor(bot_state))
        except BaseException as e:                       # nunca deixa o motor morrer em silêncio
            bot_state["running"] = False
            push_log(bot_state, f"Erro interno do motor: {str(e)[:100]}")
            time.sleep(5)


def ensure_bot():
    """Garante um motor vivo NESTE processo (também depois de um fork do gunicorn) e substitui um motor preso."""
    with _bot_lock:
        t = _bot["thread"]
        alive = t is not None and t.is_alive() and _bot["pid"] == os.getpid()
        stale = alive and bot_state["heartbeat"] > 0 and time.time() - bot_state["heartbeat"] > 30
        if alive and not stale:
            return
        bot_state["gen"] += 1
        bot_state["heartbeat"] = time.time()
        gen = bot_state["gen"]
        t = threading.Thread(target=_bot_thread, args=(gen,), name=f"nd-bot-{gen}", daemon=True)
        t.start()
        _bot["thread"], _bot["pid"] = t, os.getpid()
        push_log(bot_state, "Motor do robô sem resposta: reiniciado." if stale else "Motor do robô iniciado.")


def _diag_job(st):
    try:
        ok, steps = asyncio.run(diagnose(st))
    except BaseException as e:
        ok, steps = False, [f"✖ Erro no diagnóstico: {str(e)[:100]}"]
    bot_state["diag"] = steps
    push_log(bot_state, ("✔ " if ok else "✖ ") + steps[-1].lstrip("✔✖• ").strip())
    bot_state["diag_running"] = False


def start_diag():
    """Diagnóstico da ligação em segundo plano (não bloqueia o painel)."""
    if bot_state["diag_running"]:
        return False
    bot_state["diag_running"] = True
    bot_state["diag"] = ["A diagnosticar a ligação..."]
    threading.Thread(target=_diag_job, args=(dict(bot_state),), daemon=True).start()
    return True


ensure_bot()


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
        .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .box { background: #131b2e; border: 1px solid #1e293b; padding: 12px 8px; border-radius: 8px; text-align: center; }
        .box span { display: block; font-size: 9px; color: #64748b; text-transform: uppercase; margin-bottom: 4px; font-weight: 700; }
        .box strong { font-size: 14px; color: #22c55e; }
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
        .events { margin-top: 8px; font-size: 10px; color: #64748b; line-height: 1.5; word-break: break-word; white-space: pre-line; }
        .item { display: flex; justify-content: space-between; align-items: center; background: #0b0f19; padding: 10px 12px; border-radius: 6px; margin-bottom: 8px; border: 1px solid #1e293b; gap: 8px; }
        .badge { font-size: 10px; padding: 3px 8px; border-radius: 4px; font-weight: bold; white-space: nowrap; }
        .b-neutral { background: #1e293b; color: #94a3b8; }
        .b-long { background: #14532d; color: #4ade80; }
        .b-short { background: #7f1d1d; color: #f87171; }
        .b-warn { background: #78350f; color: #fbbf24; }
        .sub { font-size: 11px; color: #94a3b8; }
        .note { font-size: 10px; color: #f59e0b; }
        .muted { text-align: center; color: #94a3b8; font-size: 12px; margin: 14px 0; }
        .pos { color: #22c55e; } .neg { color: #ef4444; }
        .flash-up { color: #4ade80 !important; } .flash-down { color: #f87171 !important; }
        .mprice { font-size: 15px; font-weight: 800; color: #f8fafc; transition: color .6s; }
        .mode-tag { display: inline-block; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; background: #1e293b; color: #38bdf8; }
        .mode-tag.real { background: #7f1d1d; color: #fecaca; }
        .conn { display: inline-block; font-size: 11px; font-weight: 800; padding: 3px 10px; border-radius: 4px; }
        .c-ligado { background: #14532d; color: #4ade80; } .c-a_ligar { background: #78350f; color: #fbbf24; }
        .c-erro { background: #7f1d1d; color: #fecaca; } .c-sem_chaves { background: #1e293b; color: #94a3b8; }
        .errbox { margin-top: 10px; background: #2a1212; border-left: 3px solid #ef4444; color: #fecaca; padding: 10px; border-radius: 4px; font-size: 12px; line-height: 1.5; }
        .diag { margin-top: 10px; background: #0b0f19; border-left: 3px solid #38bdf8; color: #cbd5e1; padding: 10px; border-radius: 4px; font-size: 11px; line-height: 1.6; white-space: pre-line; word-break: break-word; }
        .warnbox { margin-top: 8px; background: #2a2010; border-left: 3px solid #f59e0b; color: #fde68a; padding: 8px 10px; border-radius: 4px; font-size: 11px; line-height: 1.5; }
        p { margin: 4px 0; font-size: 13px; }
        .hint { font-size: 11px; color: #64748b; margin: -4px 0 8px 0; line-height: 1.5; }
        a.logout { display: block; text-align: center; color: #64748b; font-size: 12px; margin-top: 14px; }
        canvas#chart { width: 100%; height: 200px; display: block; background: #0b0f19; border-radius: 6px; }
        .sumrow { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
        .sum { background: #131b2e; border: 1px solid #1e293b; border-radius: 8px; padding: 12px; }
        .sum h4 { margin: 0 0 6px 0; font-size: 10px; text-transform: uppercase; letter-spacing: .5px; }
        .sum .big { font-size: 15px; font-weight: 800; margin: 2px 0; }
    </style>
    <script>
        var currentTab = 'dashboard';
        var rows = {};

        function showTab(tabId) {
            currentTab = tabId;
            document.querySelectorAll('.tab-content').forEach(function (el) { el.classList.remove('active'); });
            document.querySelectorAll('.nav-btn').forEach(function (el) { el.classList.remove('active'); });
            document.getElementById(tabId).classList.add('active');
            var b = document.getElementById('btn-' + tabId);
            if (b) { b.classList.add('active'); }
            localStorage.setItem('activeNdTab', tabId);
            refresh();
        }
        function esc(s) {
            return String(s).replace(/[&<>"']/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
            });
        }
        function money(x, n) { return Number(x || 0).toFixed(n === undefined ? 2 : n); }
        function sgn(x, d) { x = Number(x || 0); return (x >= 0 ? '+' : '') + x.toFixed(d); }
        function clsn(x) { return Number(x) >= 0 ? 'pos' : 'neg'; }
        function setText(id, t) { var e = document.getElementById(id); if (e) { e.innerText = t; } }
        function trim(v) { return parseFloat(Number(v).toFixed(8)).toString(); }
        function dur(s) { s = Number(s || 0); return s >= 60 ? Math.floor(s / 60) + 'm' + (s % 60) + 's' : s + 's'; }

        var CONN = { ligado: 'LIGADA', a_ligar: 'A LIGAR...', erro: 'ERRO', sem_chaves: 'SEM CHAVES' };

        function renderCommon(d) {
            setText('clock', 'Sincronizado: ' + d.last_update);
            setText('bal-initial', money(d.initial_balance, 4));
            setText('bal-now', money(d.balance, 4));
            setText('lev-title', 'ALAVANCAGEM CONFIGURADA: ' + d.leverage + 'x');
            setText('lev-info', 'Margem por operação: ' + money(d.margin_usdt, 2) + ' USDT (usa até ' + money(d.margin_eff, 4) + ' do saldo livre)');
            setText('lev-info2', 'Posição = margem × ' + d.leverage + 'x = ' + money(d.notional, 2) + ' USDT');
            setText('free', 'Saldo livre: ' + money(d.free, 4) + ' USDT');
            setText('equity', d.equity != null ? ('Património na Bybit: ' + money(d.equity, 2) + ' USD | disponível ' + money(d.avail, 2)) : '');
            var w = document.getElementById('size-warn');
            if (d.conn === 'ligado' && d.notional < d.min_notional) {
                w.style.display = 'block';
                w.innerText = 'Saldo baixo: a ordem mínima da Bybit é cerca de ' + money(d.min_notional, 0) + ' USDT. Com ' + d.leverage + 'x precisas de pelo menos ' + money(d.min_balance, 2) + ' USDT livres. Aumenta a alavancagem ou o saldo.';
            } else { w.style.display = 'none'; }

            var cn = document.getElementById('conn');
            cn.innerText = CONN[d.conn] || d.conn;
            cn.className = 'conn c-' + d.conn;
            var eb = document.getElementById('conn-msg');
            if (d.conn === 'erro' && d.conn_msg) { eb.style.display = 'block'; eb.innerText = d.conn_msg; } else { eb.style.display = 'none'; }
            var cs = document.getElementById('conn-step');
            if (d.conn === 'a_ligar') { cs.style.display = 'block'; cs.innerText = 'A ligar: ' + (d.conn_step || 'a iniciar') + ' (' + d.conn_secs + 's)'; } else { cs.style.display = 'none'; }
            setText('motor', 'Motor do robô: ' + (d.motor_ok ? 'ativo' : 'a reiniciar...'));
            var dg = document.getElementById('diag');
            if (d.diag && d.diag.length) { dg.style.display = 'block'; dg.innerText = d.diag.join(String.fromCharCode(10)); } else { dg.style.display = 'none'; }
            document.getElementById('diag-btn').disabled = !!d.diag_running;

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
            setText('events', d.events.join(String.fromCharCode(10)));
            var btn = document.getElementById('toggle-btn');
            btn.className = 'btn-action ' + (d.running ? 'stop' : 'start');
            btn.innerText = d.running ? 'PARAR ROBÔ' : 'INICIAR ROBÔ';

            var p = d.active_position, pb = document.getElementById('pos-box');
            if (p) {
                pb.innerHTML = '<b>' + esc(p.side) + ' ' + esc(p.pair) + '</b>' + (p.trailing ? ' <span class="badge b-long">DINAMITE</span>' : '') +
                    '<p class="sub">Entrada ' + esc(p.entry) + ' | Preço ' + esc(p.price) + '</p>' +
                    '<p class="' + clsn(p.pnl_pct) + '" style="font-size:16px;font-weight:800">' + sgn(p.pnl_pct, 3) + '%</p>' +
                    '<p class="sub">SL ' + esc(p.sl) + ' | TP ' + esc(p.tp) + '</p>';
            } else {
                pb.innerHTML = '<p class="muted">Nenhuma posição ativa no momento.</p>';
            }
        }

        function renderMarket(d) {
            setText('scan-info', d.scan_info || '');
            var c = d.market_counts || {};
            setText('counts', 'LONG ' + (c.LONG || 0) + '  |  SHORT ' + (c.SHORT || 0) + '  |  NEUTRO ' + (c.NEUTRO || 0));
            var box = document.getElementById('market-list');
            var list = d.market_data || [];
            if (!list.length) {
                box.innerHTML = '<p class="muted">' + (d.conn === 'ligado' ? 'A carregar cotações...' : (d.conn === 'erro' ? 'Sem ligação à Bybit. Vê o erro no Dashboard.' : 'A aguardar a ligação à Bybit...')) + '</p>';
                rows = {};
                return;
            }
            if (box.querySelector('.muted')) { box.innerHTML = ''; rows = {}; }
            var seen = {};
            list.forEach(function (it, i) {
                seen[it.pair] = true;
                var r = rows[it.pair];
                if (!r) {
                    r = document.createElement('div');
                    r.className = 'item';
                    r.innerHTML = '<div><b style="font-size:13px" class="n"></b> <span class="mprice"></span><br><span class="sub s1"></span><br><span class="note nt"></span></div><span class="badge tr"></span>';
                    rows[it.pair] = r;
                }
                r.querySelector('.n').innerText = it.pair;
                var pe = r.querySelector('.mprice');
                pe.innerText = it.price;
                if (r._p !== undefined && it.p !== r._p) {
                    pe.className = 'mprice ' + (it.p > r._p ? 'flash-up' : 'flash-down');
                    (function (el) { setTimeout(function () { el.className = 'mprice'; }, 700); })(pe);
                }
                r._p = it.p;
                r.querySelector('.s1').innerText = '24h ' + sgn(it.chg24, 2) + '% | 1m ' + sgn(it.chg1m, 3) + '% | Vol ' + it.vr + 'x | Spread ' + it.spread + '% | ' + it.vol24;
                r.querySelector('.nt').innerText = it.note || '';
                var tr = r.querySelector('.tr');
                tr.innerText = it.trend;
                tr.className = 'badge tr ' + (it.trend === 'LONG' ? 'b-long' : (it.trend === 'SHORT' ? 'b-short' : 'b-neutral'));
                if (box.children[i] !== r) { box.insertBefore(r, box.children[i] || null); }
            });
            Object.keys(rows).forEach(function (k) {
                if (!seen[k]) { if (rows[k].parentNode) { rows[k].parentNode.removeChild(rows[k]); } delete rows[k]; }
            });
        }

        function drawChart(ch) {
            var cv = document.getElementById('chart');
            if (!cv) { return; }
            var dpr = window.devicePixelRatio || 1;
            var w = cv.clientWidth, h = cv.clientHeight;
            if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
                cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
            }
            var ctx = cv.getContext('2d');
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, w, h);
            var cap = document.getElementById('chart-cap');
            if (!ch || !ch.points || ch.points.length < 2) {
                ctx.fillStyle = '#64748b'; ctx.font = '12px sans-serif'; ctx.textAlign = 'center';
                ctx.fillText('Sem ordem aberta.', w / 2, h / 2 - 6);
                ctx.fillText('O gráfico aparece quando o robô entra numa operação.', w / 2, h / 2 + 12);
                cap.innerText = '';
                return;
            }
            var pts = ch.points, vals = [ch.entry, ch.sl, ch.tp], i;
            for (i = 0; i < pts.length; i++) { vals.push(pts[i][1]); }
            var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
            var pad = (mx - mn) * 0.08 || mx * 0.001;
            mn -= pad; mx += pad;
            var L = 4, R = 74, T = 8, B = 8, pw = w - L - R, ph = h - T - B;
            function X(k) { return L + pw * k / Math.max(1, pts.length - 1); }
            function Y(v) { return T + ph * (1 - (v - mn) / (mx - mn)); }
            function hline(v, color, label) {
                ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
                ctx.beginPath(); ctx.moveTo(L, Y(v)); ctx.lineTo(L + pw, Y(v)); ctx.stroke();
                ctx.setLineDash([]); ctx.fillStyle = color; ctx.font = '10px sans-serif'; ctx.textAlign = 'left';
                ctx.fillText(label + ' ' + trim(v), L + pw + 4, Y(v) + 3);
            }
            hline(ch.tp, '#22c55e', 'TP');
            hline(ch.entry, '#94a3b8', 'Ent');
            hline(ch.sl, '#ef4444', ch.trailing ? 'Stop' : 'SL');
            var d = ch.side === 'LONG' ? 1 : -1, last = pts[pts.length - 1][1];
            var up = d * (last - ch.entry) >= 0;
            ctx.strokeStyle = up ? '#4ade80' : '#f87171'; ctx.lineWidth = 2; ctx.beginPath();
            for (i = 0; i < pts.length; i++) { if (i === 0) { ctx.moveTo(X(i), Y(pts[i][1])); } else { ctx.lineTo(X(i), Y(pts[i][1])); } }
            ctx.stroke();
            ctx.fillStyle = up ? '#4ade80' : '#f87171';
            ctx.beginPath(); ctx.arc(X(pts.length - 1), Y(last), 3.5, 0, 6.2832); ctx.fill();
            ctx.textAlign = 'left'; ctx.font = 'bold 10px sans-serif';
            ctx.fillText(trim(last), L + pw + 4, Y(last) - 4);
            var pc = d * (last - ch.entry) / ch.entry * 100;
            cap.innerText = ch.pair + ' ' + ch.side + (ch.closed ? ' (fechada)' : ' (ao vivo)') + ' | ' + sgn(pc, 3) + '% | ' + dur(Math.round(pts[pts.length - 1][0])) + (ch.closed ? ' | PnL ' + sgn(ch.pnl, 4) + ' USDT' : '');
        }

        function renderHistory(h) {
            var s = h.stats;
            function box(id, o, c) {
                document.getElementById(id).innerHTML =
                    '<div class="big ' + c + '">' + sgn(o.usdt, 4) + ' USDT</div>' +
                    '<div class="big ' + c + '" style="font-size:13px">' + sgn(o.pct, 2) + ' %</div>' +
                    '<div class="sub">' + o.n + ' operações</div>';
            }
            box('sum-win', s.wins, 'pos');
            box('sum-loss', s.losses, 'neg');
            var t = s.total;
            document.getElementById('sum-total').innerHTML =
                '<div class="big ' + clsn(t.usdt) + '">' + sgn(t.usdt, 4) + ' USDT &nbsp; ' + sgn(t.pct, 2) + ' %</div>' +
                '<div class="sub">' + t.n + ' operações | acerto ' + t.winrate + '%</div>';
            var hl = document.getElementById('history-list');
            if (!h.trades.length) { hl.innerHTML = '<p class="muted">Nenhuma operação fechada ainda.</p>'; return; }
            var x = '';
            h.trades.forEach(function (t) {
                var c = clsn(t.pnl);
                x += '<div class="item"><div><b>' + esc(t.side) + ' ' + esc(t.pair) + '</b> <span class="sub">' + esc(t.reason) + '</span><br>' +
                    '<span class="sub">Aberto ' + esc(t.opened) + '<br>Fechado ' + esc(t.closed) + ' (' + dur(t.dur) + ')</span><br>' +
                    '<span class="sub">Qtd ' + esc(trim(t.qty)) + ' | Posição ' + money(t.notional, 2) + ' USDT | ' + esc(t.entry) + ' → ' + esc(t.exit) + '</span></div>' +
                    '<div style="text-align:right"><b class="' + c + '">' + sgn(t.pnl, 4) + ' USDT</b><br><span class="' + c + '" style="font-size:12px">' + sgn(t.pnl_pct, 2) + ' %</span></div></div>';
            });
            hl.innerHTML = x;
        }

        var busy = false;
        function refresh() {
            if (busy) { return; }
            busy = true;
            var tab = currentTab;
            var jobs = [fetch('/api/state?tab=' + tab, { credentials: 'same-origin' })];
            if (tab === 'historico') { jobs.push(fetch('/api/history', { credentials: 'same-origin' })); }
            Promise.all(jobs).then(function (rs) {
                if (rs[0].status === 401) { location.reload(); return null; }
                return Promise.all(rs.map(function (r) { return r.json(); }));
            }).then(function (ds) {
                busy = false;
                if (!ds) { return; }
                renderCommon(ds[0]);
                if (tab === 'mercado') { renderMarket(ds[0]); }
                if (tab === 'dashboard') { drawChart(ds[0].chart); }
                if (tab === 'historico' && ds[1]) { renderHistory(ds[1]); }
            }).catch(function () { busy = false; });
        }

        window.onload = function () {
            var saved = localStorage.getItem('activeNdTab');
            if (saved && document.getElementById(saved)) { showTab(saved); } else { refresh(); }
            setInterval(refresh, 1000);
        };
    </script>
</head>
<body>
    <div class="container">
        <h1>ND-SCALPING</h1>
        <div class="clock" id="clock">Sincronizado: ...</div>

        <div id="dashboard" class="tab-content active">
            <div class="grid2">
                <div class="box"><span>INICIAL (USDT)</span><strong id="bal-initial">0.0000</strong></div>
                <div class="box"><span>ATUAL (USDT)</span><strong id="bal-now">0.0000</strong></div>
            </div>

            <div class="card">
                <h3>LIGAÇÃO À BYBIT</h3>
                <span class="conn c-sem_chaves" id="conn">...</span>
                <span class="mode-tag" id="mode-tag" style="margin-left:6px">{{ modes[mode] }}</span>
                <div class="errbox" id="conn-msg" style="display:none"></div>
                <p class="sub" id="conn-step" style="display:none;margin-top:8px"></p>
                <p class="sub" id="motor" style="margin-top:6px"></p>
                <div class="diag" id="diag" style="display:none"></div>
                <form action="/diag" method="POST" style="margin-top:10px">
                    <button type="submit" class="btn-save btn-test" id="diag-btn">Diagnóstico da ligação</button>
                </form>
            </div>

            <div class="card" id="pos-box"><p class="muted">Nenhuma posição ativa no momento.</p></div>

            <div class="card">
                <h3 id="lev-title">ALAVANCAGEM CONFIGURADA: {{ leverage }}x</h3>
                <p class="sub" id="lev-info"></p>
                <p class="sub" id="lev-info2"></p>
                <p class="sub" id="free"></p>
                <p class="sub" id="equity"></p>
                <div class="warnbox" id="size-warn" style="display:none"></div>
            </div>

            <div class="grid2">
                <div class="box"><span>STATUS</span><strong id="status" style="font-size: 12px; color: #ef4444;">PARADO</strong></div>
                <div class="box"><span>PNL REALIZADO</span><strong id="pnl" style="font-size: 12px;">+0.0000</strong></div>
            </div>

            <div class="card">
                <h3>ESTADO / LOG DA API:</h3>
                <div class="log-box" id="log-box">...</div>
                <div class="events" id="events"></div>
            </div>

            <form action="/toggle" method="POST" style="margin-top: 15px;">
                <button type="submit" id="toggle-btn" class="btn-action {{ 'stop' if running else 'start' }}">{{ 'PARAR ROBÔ' if running else 'INICIAR ROBÔ' }}</button>
            </form>
            <p class="hint" style="text-align:center;margin-top:8px">O mercado e o saldo sincronizam sempre que há ligação. O robô só abre operações depois de INICIAR. Ao parar, a posição aberta é fechada a mercado.</p>

            <div class="card" style="margin-top:12px">
                <h3>EVOLUÇÃO DA ORDEM ABERTA</h3>
                <canvas id="chart"></canvas>
                <p class="sub" id="chart-cap" style="margin-top:6px;text-align:center"></p>
            </div>
        </div>

        <div id="mercado" class="tab-content">
            <div class="card">
                <h3>MERCADO SCALPING ({{ total_pairs }} PARES &lt; 1 USDT)</h3>
                <p class="sub" id="scan-info"></p>
                <p class="sub" id="counts" style="margin-bottom:8px;font-weight:700"></p>
                <div id="market-list"><p class="muted">A carregar cotações...</p></div>
            </div>
        </div>

        <div id="historico" class="tab-content">
            <div class="sumrow">
                <div class="sum"><h4 class="pos">Operações positivas</h4><div id="sum-win"></div></div>
                <div class="sum"><h4 class="neg">Operações negativas</h4><div id="sum-loss"></div></div>
            </div>
            <div class="sum" style="margin-bottom:10px"><h4 style="color:#38bdf8">Geral (soma dos dois)</h4><div id="sum-total"></div>
                <p class="hint" style="margin:6px 0 0 0">A percentagem é sobre a margem usada em cada operação (retorno com alavancagem).</p></div>
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
                    <input type="number" name="margin_usdt" value="{{ margin }}" min="0.1" step="0.1" required>
                    <p class="hint">É a <b>margem</b>: o valor do teu saldo que entra em cada operação. A posição é multiplicada pela alavancagem (margem × alavancagem). Ex.: 5 USDT × 18x = 90 USDT. Se o saldo livre for menor, o robô usa no máximo 96% dele (o resto cobre as taxas).</p>

                    <button type="submit" name="action" value="save" class="btn-save">Guardar Definições</button>
                    <button type="submit" name="action" value="test" class="btn-save btn-test">Guardar e testar ligação (resultado no Dashboard)</button>
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
