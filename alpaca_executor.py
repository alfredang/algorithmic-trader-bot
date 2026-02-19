
import logging
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

logger = logging.getLogger(__name__)

class AlpacaExecutor:
    """
    Executes trades on Alpaca Paper Trading API.
    """

    def __init__(self, api_key, secret_key, paper=True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.client = None
        self.connected = False

    def connect(self):
        """Connect to Alpaca API."""
        if not self.api_key or not self.secret_key:
            logger.error("Alpaca API keys not found.")
            return False
            
        try:
            self.client = TradingClient(self.api_key, self.secret_key, paper=self.paper)
            # minimal check
            account = self.client.get_account()
            if account.status == 'ACTIVE':
                self.connected = True
                logger.info("Connected to Alpaca Paper Trading")
                return True
            else:
                logger.error(f"Alpaca account status: {account.status}")
                return False
        except Exception as e:
            logger.error(f"Failed to connect to Alpaca: {e}")
            return False

    def get_account_info(self):
        """Return account info from Alpaca."""
        if not self.connected:
            return None
        
        try:
            account = self.client.get_account()
            return {
                "id": account.id,
                "cash": float(account.cash),
                "portfolio_value": float(account.portfolio_value),
                "buying_power": float(account.buying_power),
                "multiplier": float(account.multiplier),
                "long_market_value": float(account.long_market_value),
                "short_market_value": float(account.short_market_value),
                "equity": float(account.equity),
            }
        except Exception as e:
            logger.error(f"Error fetching account info: {e}")
            return None

    def get_positions(self):
        """Return current positions as a DataFrame."""
        if not self.connected:
            return pd.DataFrame()

        try:
            positions = self.client.get_all_positions()
            if not positions:
                return pd.DataFrame(columns=[
                    "Ticker", "Qty", "Avg Cost", "Market Value", "P/L", "P/L %"
                ])

            rows = []
            for pos in positions:
                rows.append({
                    "Ticker": pos.symbol,
                    "Qty": float(pos.qty),
                    "Avg Cost": float(pos.avg_entry_price),
                    "Market Value": float(pos.market_value),
                    "P/L": float(pos.unrealized_pl),
                    "P/L %": float(pos.unrealized_plpc) * 100
                })
            return pd.DataFrame(rows)
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return pd.DataFrame()

    def get_position_qty(self, ticker):
        """Get qty for a ticker."""
        if not self.connected:
            return 0
        
        try:
            # We iterate because get_open_position raises 404 if not found
            positions = self.client.get_all_positions()
            for pos in positions:
                if pos.symbol == ticker:
                    return float(pos.qty)
            return 0
        except Exception:
            return 0

    def place_buy_order(self, ticker, qty):
        """Place a market buy order."""
        if not self.connected:
            return None

        req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        try:
            order = self.client.submit_order(req)
            logger.info(f"Submitted BUY {ticker} x{qty} (id={order.id})")
            return order.id
        except Exception as e:
            logger.error(f"Failed to submit BUY order: {e}")
            return None

    def place_sell_order(self, ticker, qty):
        """Place a market sell order."""
        if not self.connected:
            return None

        req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )
        try:
            order = self.client.submit_order(req)
            logger.info(f"Submitted SELL {ticker} x{qty} (id={order.id})")
            return order.id
        except Exception as e:
            logger.error(f"Failed to submit SELL order: {e}")
            return None

    def execute_signal(self, signal, ticker, current_price, capital=None, position_size_pct=0.95):
        """
        Execute signal using Alpaca.
        Args:
            signal: "BUY", "SELL", or None.
            ticker: Stock symbol
            current_price: float. Needed to calculate qty based on capital.
            capital: float. If None, uses current buying power.
            position_size_pct: float. Fraction of capital to use.
        """
        if not self.connected or signal is None:
            return None

        if signal == "BUY":
            # Determine capital to use
            if capital is None:
                # Use available buying power or cash
                account = self.get_account_info()
                if not account:
                    return None
                capital = float(account["buying_power"])

            # Calculate quantity to buy
            allocation = capital * position_size_pct
            qty = int(allocation / current_price)

            if qty <= 0:
                logger.warning(f"Insufficient capital/buying power to buy {ticker} (alloc=${allocation:.2f})")
                return None

            order_id = self.place_buy_order(ticker, qty)
            if order_id is not None:
                return {
                    "action": "BUY",
                    "qty": qty,
                    "price": current_price,
                    "order_id": str(order_id)
                }
            else:
                return None

        elif signal == "SELL":
            qty = self.get_position_qty(ticker)
            if qty <= 0:
                logger.warning(f"No position to sell for {ticker}")
                return None

            order_id = self.place_sell_order(ticker, qty)
            if order_id is not None:
                return {
                    "action": "SELL",
                    "qty": qty,
                    "price": current_price,
                    "order_id": str(order_id)
                }
            else:
                return None

        return None
