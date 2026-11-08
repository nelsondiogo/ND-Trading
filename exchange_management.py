import ccxt

def get_exchange(bot_state):
    key = str(bot_state.get("api_key", "")).strip()
    secret = str(bot_state.get("api_secret", "")).strip()

    if not key or not secret:
        return None

    try:
        exchange = ccxt.bybit({
            'apiKey': key,
            'secret': secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'linear',
                'adjustForTimeDifference': True
            }
        })
        
        if bot_state.get("is_demo", True):
            exchange.urls['api'] = exchange.urls['test']
            exchange.set_sandbox_mode(True)
            
        exchange.load_markets()
        return exchange
    except Exception as e:
        bot_state["log"] = f"Erro API: {str(e)[:40]}"
        return None
