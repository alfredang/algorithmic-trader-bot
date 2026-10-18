"""Market-making simulation with inventory skew (course Topic 2.2).

Each bar the market maker quotes around the previous close (the 'mid'):

    reservation = mid x (1 - skew_bps x inventory / max_inventory / 1e4)
    bid = reservation x (1 - half_spread_bps / 1e4);  ask = reservation x (1 + half_spread_bps / 1e4)

A quote fills when the bar trades through it (low <= bid buys, high >= ask sells),
one clip per side per bar, subject to an inventory limit. Being long pushes both
quotes down (sell more readily), being short pushes them up - the inventory skew.
P&L is marked to the bar close; adverse selection appears as losses in trending bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def simulate(bars: pd.DataFrame, half_spread_bps: float = 10.0, clip: float = 100, max_inventory: float = 1000,
             skew_bps: float = 15.0, fee_bps: float = 0.0, initial_capital: float = 100_000.0) -> dict:
    o, h, l, c = (bars[k].values for k in ("open", "high", "low", "close"))
    cash, inv = initial_capital, 0.0
    eq, invs, rows = [], [], []
    spread_pnl = 0.0
    buys = sells = 0
    for i in range(len(c)):
        if i == 0:
            eq.append(cash)
            invs.append(0.0)
            continue
        mid = c[i - 1]
        res = mid * (1 - skew_bps * inv / max_inventory / 1e4)
        bid, ask = res * (1 - half_spread_bps / 1e4), res * (1 + half_spread_bps / 1e4)
        if l[i] <= bid and inv + clip <= max_inventory:
            px = min(o[i], bid)
            cash -= clip * px * (1 + fee_bps / 1e4)
            inv += clip
            buys += 1
            spread_pnl += clip * (mid - px)
            rows.append({"time": str(bars.index[i]), "side": "buy", "price": float(px), "qty": clip})
        if h[i] >= ask and inv - clip >= -max_inventory:
            px = max(o[i], ask)
            cash += clip * px * (1 - fee_bps / 1e4)
            inv -= clip
            sells += 1
            spread_pnl += clip * (px - mid)
            rows.append({"time": str(bars.index[i]), "side": "sell", "price": float(px), "qty": clip})
        eq.append(cash + inv * c[i])
        invs.append(inv)
    equity = pd.Series(eq, index=bars.index, name="equity")
    inventory = pd.Series(invs, index=bars.index, name="inventory")
    return {"equity": equity, "inventory": inventory, "fills": rows, "n_buys": buys, "n_sells": sells,
            "spread_captured": float(spread_pnl), "final_inventory": float(inv),
            "inventory_pnl": float(equity.iloc[-1] - initial_capital - spread_pnl),
            "max_abs_inventory": float(np.abs(invs).max()) if invs else 0.0}


def signals_from_inventory(inventory: pd.Series, max_inventory: float) -> pd.Series:
    """Express the market maker's inventory as a position fraction (for exposure metrics)."""
    return (inventory / max_inventory).clip(-1, 1)
