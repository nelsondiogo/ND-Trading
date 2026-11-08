import time

def execute_trading_logic(exchange, bot_state):
    try:
        bal = exchange.fetch_balance()
        total = float(bal.get('total', {}).get('USDT', 0.0))
        if total > 0:
            if bot_state["initial_balance"] == 0.0:
                bot_state["initial_balance"] = total
            bot_state["balance"] = total

        from config import PAIRS
        m_list = []
        for sym in PAIRS:
            ticker = exchange.fetch_ticker(sym)
            coin_name = sym.split('/')[0]
            price = ticker.get('last', 0.0)
            
            m_list.append({
                "pair": coin_name, 
                "price": price,
                "rsi": "50.0",
                "status": "NEUTRO"
            })
        
        bot_state["market_data"] = m_list

        free_usdt = float(bal.get('free', {}).get('USDT', 0.0))
        if free_usdt < 0.1 and bot_state["running"]:
            bot_state["log"] = "Aviso: Saldo livre insuficiente para ordens."

    except Exception:
        pass
