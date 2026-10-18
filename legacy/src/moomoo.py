import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LocalTradeSimulator:
    def __init__(self):
        # We'll use Streamlit session state to persist the portfolio, 
        # so this class just provides the logic for "placing" orders.
        pass

    def place_order(self, portfolio, symbol, qty, side, current_price):
        """
        Simulates an order and updates the provided portfolio dictionary.
        """
        try:
            order_value = qty * current_price
            
            if side.upper() == 'BUY':
                if portfolio['cash'] < order_value:
                    return False, "Insufficient virtual cash balance."
                
                portfolio['cash'] -= order_value
                portfolio['positions'][symbol] = portfolio['positions'].get(symbol, 0) + qty
                msg = f"Simulated BUY of {qty} {symbol} at ${current_price:.2f}"
            
            elif side.upper() == 'SELL':
                current_qty = portfolio['positions'].get(symbol, 0)
                if current_qty < qty:
                    return False, f"Insufficient position in {symbol} to sell."
                
                portfolio['cash'] += order_value
                portfolio['positions'][symbol] -= qty
                if portfolio['positions'][symbol] == 0:
                    del portfolio['positions'][symbol]
                msg = f"Simulated SELL of {qty} {symbol} at ${current_price:.2f}"
            
            else:
                return False, "Invalid side. Use BUY or SELL."

            # Log transaction
            transaction = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": current_price
            }
            portfolio['history'].append(transaction)
            logger.info(msg)
            return True, msg

        except Exception as e:
            logger.error(f"Simulator error: {e}")
            return False, str(e)
