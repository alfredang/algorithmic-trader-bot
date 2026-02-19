# executor.py — Simulated paper trade executor (no broker connection needed)

import logging
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)


class PaperTradeExecutor:
    """
    Simulates paper trading locally.

    Tracks cash, positions, and order history in memory.
    No external broker connection required.
    """

    def __init__(self, initial_capital=100_000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}  # {ticker: {"qty": int, "avg_cost": float}}
        self.order_history = []  # list of order dicts
        self._next_order_id = 1
        self.connected = True  # always "connected" in simulation

    def connect(self):
        """No-op for simulation. Always returns True."""
        self.connected = True
        logger.info("Simulated paper trading executor ready")
        return True

    def disconnect(self):
        """No-op for simulation."""
        self.connected = False
        logger.info("Simulated paper trading executor stopped")

    def get_account_info(self):
        """
        Return simulated account information.

        Returns dict with cash, total_assets, market_val.
        Note: market_val uses avg_cost since we don't have live prices here.
        Use get_account_info_with_price() for mark-to-market.
        """
        market_val = sum(
            pos["qty"] * pos["avg_cost"]
            for pos in self.positions.values()
        )
        return {
            "cash": self.cash,
            "total_assets": self.cash + market_val,
            "market_val": market_val,
        }

    def get_account_info_with_price(self, prices):
        """
        Return account info with mark-to-market using live prices.

        Args:
            prices: dict of {ticker: current_price}
        """
        market_val = sum(
            pos["qty"] * prices.get(ticker, pos["avg_cost"])
            for ticker, pos in self.positions.items()
        )
        return {
            "cash": self.cash,
            "total_assets": self.cash + market_val,
            "market_val": market_val,
        }

    def get_positions(self):
        """Return current positions as a DataFrame."""
        if not self.positions:
            return pd.DataFrame(columns=[
                "Ticker", "Qty", "Avg Cost", "Market Value",
            ])

        rows = []
        for ticker, pos in self.positions.items():
            rows.append({
                "Ticker": ticker,
                "Qty": pos["qty"],
                "Avg Cost": f"${pos['avg_cost']:.2f}",
                "Market Value": f"${pos['qty'] * pos['avg_cost']:,.2f}",
            })
        return pd.DataFrame(rows)

    def get_position_qty(self, ticker):
        """Get current quantity held for a specific stock. Returns 0 if none."""
        pos = self.positions.get(ticker)
        if pos is None:
            return 0
        return pos["qty"]

    def place_buy_order(self, ticker, qty, price):
        """
        Simulate a buy order. Deducts cash, updates position.

        Returns order_id string on success, None if insufficient cash.
        """
        cost = qty * price
        if cost > self.cash:
            logger.warning(
                f"Insufficient cash for BUY {ticker} x{qty} @ ${price:.2f} "
                f"(need ${cost:,.2f}, have ${self.cash:,.2f})"
            )
            return None

        self.cash -= cost
        order_id = f"SIM-{self._next_order_id:06d}"
        self._next_order_id += 1

        # Update position
        if ticker in self.positions:
            existing = self.positions[ticker]
            total_qty = existing["qty"] + qty
            total_cost = existing["qty"] * existing["avg_cost"] + cost
            self.positions[ticker] = {
                "qty": total_qty,
                "avg_cost": total_cost / total_qty,
            }
        else:
            self.positions[ticker] = {"qty": qty, "avg_cost": price}

        # Record order
        self.order_history.append({
            "order_id": order_id,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": "BUY",
            "ticker": ticker,
            "qty": qty,
            "price": price,
            "total": cost,
            "status": "Filled",
        })

        logger.info(
            f"BUY {ticker} x{qty} @ ${price:.2f} = ${cost:,.2f} "
            f"(order_id={order_id})"
        )
        return order_id

    def place_sell_order(self, ticker, qty, price):
        """
        Simulate a sell order. Adds cash, reduces/removes position.

        Returns order_id string on success, None if insufficient shares.
        """
        pos = self.positions.get(ticker)
        if pos is None or pos["qty"] < qty:
            available = pos["qty"] if pos else 0
            logger.warning(
                f"Insufficient shares for SELL {ticker} x{qty} "
                f"(have {available})"
            )
            return None

        proceeds = qty * price
        self.cash += proceeds
        order_id = f"SIM-{self._next_order_id:06d}"
        self._next_order_id += 1

        # Update position
        pos["qty"] -= qty
        if pos["qty"] == 0:
            del self.positions[ticker]

        # Record order
        self.order_history.append({
            "order_id": order_id,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": "SELL",
            "ticker": ticker,
            "qty": qty,
            "price": price,
            "total": proceeds,
            "status": "Filled",
        })

        logger.info(
            f"SELL {ticker} x{qty} @ ${price:.2f} = ${proceeds:,.2f} "
            f"(order_id={order_id})"
        )
        return order_id

    def execute_signal(self, signal, ticker, current_price, capital=None, position_size_pct=0.95):
        """
        Execute a trading signal.

        Args:
            signal: "BUY", "SELL", or None.
            ticker: Stock symbol.
            current_price: Current market price.
            capital: Override cash for sizing (uses self.cash if None).
            position_size_pct: Fraction of capital to use for buy.

        Returns dict with action details, or None if no action.
        """
        if signal is None:
            return None

        if capital is None:
            capital = self.cash

        if signal == "BUY":
            qty = int((capital * position_size_pct) / current_price)
            if qty <= 0:
                logger.warning(f"Insufficient capital to buy {ticker}")
                return None
            order_id = self.place_buy_order(ticker, qty, current_price)
            if order_id is None:
                return None
            return {
                "action": "BUY",
                "qty": qty,
                "price": current_price,
                "order_id": order_id,
            }

        elif signal == "SELL":
            qty = self.get_position_qty(ticker)
            if qty <= 0:
                logger.warning(f"No position to sell for {ticker}")
                return None
            order_id = self.place_sell_order(ticker, qty, current_price)
            if order_id is None:
                return None
            return {
                "action": "SELL",
                "qty": qty,
                "price": current_price,
                "order_id": order_id,
            }

        return None
