"""Trading-cost models (course Topic 4.2 / Lab 15).

Costs charged on every fill (dollars):

    commission = max(min_commission, shares x commission_per_share + notional x commission_bps)
    spread     = notional x spread_bps / 2        (you cross half the quoted spread)
    slippage   = notional x slippage_bps          (market impact / delay)
    reg fees   = SELL notional x sec_fee_rate + min(shares sold x taf_per_share, taf_max)
                 (US SEC Section 31 fee and FINRA Trading Activity Fee style charges;
                  rates change - check the current published rates before relying on them)
    borrow     = short notional x borrow_bps_annual / 252 per bar held short
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace

SEC_FEE = 27.80 / 1e6        # illustrative Section 31 rate ($ per $ of sell notional)
FINRA_TAF = 0.000166         # illustrative TAF per share sold
COST_KEYS = ["commission", "spread", "slippage", "reg_fees", "borrow"]


@dataclass
class CostModel:
    name: str = "Zero cost"
    commission_per_share: float = 0.0
    commission_bps: float = 0.0
    min_commission: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    sec_fee_rate: float = 0.0
    taf_per_share: float = 0.0
    taf_max: float = 8.30
    borrow_bps_annual: float = 0.0

    def trade_cost(self, notional: float, price: float, is_sell: bool) -> dict:
        """Cost breakdown in dollars for one fill of ``notional`` dollars at ``price``."""
        out = dict.fromkeys(COST_KEYS, 0.0)
        if notional <= 0 or price <= 0:
            return out
        shares = notional / price
        commission = shares * self.commission_per_share + notional * self.commission_bps / 1e4
        if self.commission_per_share or self.commission_bps or self.min_commission:
            commission = max(commission, self.min_commission)
        reg = 0.0
        if is_sell:
            reg = notional * self.sec_fee_rate + min(shares * self.taf_per_share, self.taf_max)
        out.update(commission=commission, spread=notional * self.spread_bps / 2 / 1e4,
                   slippage=notional * self.slippage_bps / 1e4, reg_fees=reg)
        return out

    def borrow_cost(self, short_notional: float, periods: int = 252) -> float:
        return abs(short_notional) * self.borrow_bps_annual / 1e4 / periods

    def one_way_bps(self) -> float:
        """Approximate one-way cost in bps excluding fixed commissions (for diagnostics)."""
        return self.spread_bps / 2 + self.slippage_bps + self.commission_bps

    def scaled(self, factor: float) -> CostModel:
        return replace(self, name=f"{self.name} x{factor:g}",
                       commission_per_share=self.commission_per_share * factor,
                       commission_bps=self.commission_bps * factor, min_commission=self.min_commission * factor,
                       spread_bps=self.spread_bps * factor, slippage_bps=self.slippage_bps * factor,
                       sec_fee_rate=self.sec_fee_rate * factor, taf_per_share=self.taf_per_share * factor,
                       borrow_bps_annual=self.borrow_bps_annual * factor)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> CostModel:
        if not d:
            return cls()
        if isinstance(d, str):
            return COST_PRESETS[d]
        if "preset" in d:
            base = COST_PRESETS.get(d["preset"], cls())
            overrides = {k: v for k, v in d.items() if k != "preset" and k in {f.name for f in fields(cls)}}
            return replace(base, **overrides) if overrides else base
        known = {f.name for f in fields(cls)}
        return cls(**{k: (v if k == "name" else float(v)) for k, v in d.items() if k in known})


COST_PRESETS: dict[str, CostModel] = {
    "zero": CostModel(),
    # Alpaca: commission-free US equities; you still pay spread, slippage and reg fees on sells
    "alpaca_retail": CostModel("Alpaca commission-free", spread_bps=1.0, slippage_bps=1.0,
                               sec_fee_rate=SEC_FEE, taf_per_share=FINRA_TAF, borrow_bps_annual=50.0),
    # A per-share institutional broker (illustrative)
    "per_share_broker": CostModel("Per-share broker", commission_per_share=0.005, min_commission=1.0,
                                  spread_bps=2.0, slippage_bps=2.0, sec_fee_rate=SEC_FEE,
                                  taf_per_share=FINRA_TAF, borrow_bps_annual=50.0),
    # A high-cost retail / offshore route (illustrative)
    "high_cost": CostModel("High-cost route", commission_bps=10.0, spread_bps=5.0, slippage_bps=5.0,
                           sec_fee_rate=SEC_FEE, taf_per_share=FINRA_TAF, borrow_bps_annual=300.0),
}
