# utils.py — Logging, formatting, validation helpers

import logging
import pandas as pd
from datetime import datetime


def setup_logging(level="INFO"):
    """Configure root logger with timestamped format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger()


def format_currency(value):
    """Format as currency: '$1,234.56'."""
    return f"${value:,.2f}"


def format_percentage(value):
    """Format float as percentage: 0.1234 -> '12.34%'."""
    return f"{value * 100:.2f}%"


def format_number(value, decimals=2):
    """Format with thousand separators and fixed decimals."""
    return f"{value:,.{decimals}f}"


def validate_date_range(start, end):
    """Validate start < end and both are valid yyyy-MM-dd strings."""
    try:
        s = datetime.strptime(str(start), "%Y-%m-%d")
        e = datetime.strptime(str(end), "%Y-%m-%d")
        return s < e
    except ValueError:
        return False


def validate_sma_windows(short, long):
    """Validate short < long and both > 0."""
    return 0 < short < long


def df_to_trade_log_display(trade_records):
    """Convert list of TradeRecord dataclasses to a display-ready DataFrame."""
    if not trade_records:
        return pd.DataFrame(columns=[
            "Entry Date", "Entry Price", "Exit Date", "Exit Price",
            "Qty", "P&L", "Return %", "Commission", "Slippage",
        ])

    rows = []
    for t in trade_records:
        rows.append({
            "Entry Date": t.entry_date,
            "Entry Price": f"${t.entry_price:.2f}",
            "Exit Date": t.exit_date,
            "Exit Price": f"${t.exit_price:.2f}",
            "Qty": t.qty,
            "P&L": f"${t.pnl:,.2f}",
            "Return %": f"{t.return_pct * 100:.2f}%",
            "Commission": f"${t.commission_paid:.2f}",
            "Slippage": f"${t.slippage_cost:.2f}",
        })
    return pd.DataFrame(rows)
