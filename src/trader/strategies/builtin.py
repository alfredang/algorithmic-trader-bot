"""Built-in strategy library - every strategy taught in the course.

Explanations reuse the course "How the algorithm works" text (visual_data.ALGO_EXPLAIN).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from trader.content.course import ALGO_EXPLAIN
from trader.core import indicators as ta
from trader.core import market_making as mm
from trader.core import ml as ML
from trader.core import pairs as PR
from trader.core import regime as RG
from trader.strategies.base import Strategy, StrategyInfo, enter_exit, flat_until_ready


def _explain(title: str) -> dict:
    e = ALGO_EXPLAIN.get(title, {})
    return {"how": e.get("How it works", ""), "rule": e.get("Rule", ""), "works_best": e.get("Works best when", ""),
            "watch_out": e.get("Watch out for", ""), "course_ref": e.get("kicker", "")}


MA = _explain("Algorithm: Moving-Average Crossover (Trend Following)")
BB = _explain("Algorithm: Bollinger Band Mean Reversion")
OSC = _explain("Algorithm: RSI and MACD Momentum Oscillators")
XS = _explain("Algorithm: Cross-Sectional Momentum")
DC = _explain("Algorithm: Donchian Channel Breakout")
EX = _explain("Algorithm: VWAP and TWAP Execution")
MM = _explain("Algorithm: Market Making")
LR = _explain("Algorithm: Logistic Regression for Direction")
RF = _explain("Algorithm: Decision Tree and Random Forest")
XG = _explain("Algorithm: Gradient Boosting (XGBoost)")
KM = _explain("Algorithm: K-Means Clustering for Market Regimes")
PAIRS = _explain("Algorithm: Pairs Trading (Hedged Statistical Arbitrage)")

SIGNAL_BASES = ["ema_cross", "sma_cross", "trend_filter", "ts_momentum", "donchian_breakout", "macd_cross"]


# =========================================================================== benchmark
class BuyAndHold(Strategy):
    name = "Buy and hold (benchmark)"
    params = {}
    info = StrategyInfo("buy_hold", name, family="Benchmark", holding_period="Position",
                        summary="Buy at the first next-bar open and hold - the benchmark every strategy must beat.",
                        how="Invest 100% of equity on the first bar and never trade again.",
                        rule="Always long.", works_best="Long rising markets; lowest cost and turnover.",
                        watch_out="Full exposure to every crash - compare drawdowns, not just returns.",
                        course_ref="TOPIC 2 · K3", pine=True)

    def generate_signals(self, data):
        return pd.Series(1.0, index=data.index)


# =========================================================================== trend
class SMACross(Strategy):
    name = "SMA crossover"
    params = {"fast": {"default": 50, "min": 2, "max": 300, "help": "Fast simple moving average length (bars)"},
              "slow": {"default": 200, "min": 3, "max": 400, "help": "Slow simple moving average length (bars)"}}
    info = StrategyInfo("sma_cross", name, summary="Golden cross / death cross on two simple moving averages.",
                        pine=True, **MA)

    def generate_signals(self, data):
        f, s = ta.sma(data["close"], self.p.fast), ta.sma(data["close"], self.p.slow)
        return flat_until_ready(f > s, f, s)


class EMACross(Strategy):
    name = "EMA crossover"
    params = {"fast": {"default": 10, "min": 2, "max": 200, "help": "Fast EMA length"},
              "slow": {"default": 30, "min": 3, "max": 400, "help": "Slow EMA length"}}
    info = StrategyInfo("ema_cross", name, summary="Long while the fast EMA is above the slow EMA (the course bot's default).",
                        pine=True, **MA)

    def generate_signals(self, data):
        f, s = ta.ema(data["close"], self.p.fast), ta.ema(data["close"], self.p.slow)
        return flat_until_ready(f > s, f, s)


class TrendFilter(Strategy):
    name = "Trend filter (close > SMA)"
    params = {"window": {"default": 200, "min": 10, "max": 400, "help": "SMA length"}}
    info = StrategyInfo("trend_filter", name, summary="Long while the close is above its long moving average.",
                        pine=True, **MA)

    def generate_signals(self, data):
        m = ta.sma(data["close"], self.p.window)
        return flat_until_ready(data["close"] > m, m)


class MACDCross(Strategy):
    name = "MACD signal-line cross"
    params = {"fast": {"default": 12, "min": 2, "max": 100}, "slow": {"default": 26, "min": 3, "max": 200},
              "signal": {"default": 9, "min": 2, "max": 50, "help": "Signal-line EMA length"}}
    info = StrategyInfo("macd_cross", name, family="Momentum and breakout", holding_period="Swing",
                        summary="Long while the MACD line is above its signal line.", pine=True, **OSC)

    def generate_signals(self, data):
        m = ta.macd(data["close"], self.p.fast, self.p.slow, self.p.signal)
        return flat_until_ready(m["macd"] > m["signal"], m["macd"], m["signal"])


# =========================================================================== mean reversion / oscillators
class RSIThreshold(Strategy):
    name = "RSI oversold / overbought"
    params = {"window": {"default": 14, "min": 2, "max": 50}, "oversold": {"default": 30, "min": 1, "max": 50},
              "overbought": {"default": 70, "min": 50, "max": 99},
              "allow_short": {"default": False, "help": "Short when overbought instead of going flat"}}
    info = StrategyInfo("rsi_threshold", name, family="Mean reversion", holding_period="Swing",
                        summary="Buy when RSI(14) < 30 and sell when RSI > 70 (optionally short above 70).",
                        pine=True, **OSC)

    def generate_signals(self, data):
        r = ta.rsi(data["close"], self.p.window)
        state = pd.Series(np.nan, index=data.index)
        state[r < self.p.oversold] = 1.0
        state[r > self.p.overbought] = -1.0 if self.p.allow_short else 0.0
        return state.ffill().fillna(0.0)


class RSI2Reversion(Strategy):
    name = "RSI(2) mean reversion"
    params = {"n": {"default": 2, "min": 2, "max": 14, "help": "RSI length"},
              "entry": {"default": 10, "min": 1, "max": 50, "help": "Buy when RSI(n) falls below this"},
              "exit": {"default": 70, "min": 30, "max": 99, "help": "Sell when RSI(n) rises above this"}}
    info = StrategyInfo("rsi2_reversion", name, family="Mean reversion", holding_period="Swing",
                        summary="Larry Connors-style short-term reversion: buy deep RSI(2) dips, sell on the bounce.",
                        pine=True, **OSC)

    def generate_signals(self, data):
        r = ta.rsi(data["close"], self.p.n)
        return enter_exit(r < self.p.entry, r > self.p.exit)


class BollingerReversion(Strategy):
    name = "Bollinger Band mean reversion"
    params = {"window": {"default": 20, "min": 5, "max": 100}, "k": {"default": 2.0, "min": 0.5, "max": 4.0, "step": 0.1}}
    info = StrategyInfo("bollinger_reversion", name, family="Mean reversion", holding_period="Swing",
                        summary="Buy a close below the lower band; exit when the price returns to the middle band.",
                        pine=True, default_symbols=["KO"], **BB)

    def generate_signals(self, data):
        b = ta.bollinger(data["close"], self.p.window, self.p.k)
        return enter_exit(data["close"] < b["lower"], data["close"] > b["middle"])


class BollingerBreakout(Strategy):
    name = "Bollinger Band breakout"
    params = {"window": {"default": 20, "min": 5, "max": 100}, "k": {"default": 2.0, "min": 0.5, "max": 4.0, "step": 0.1}}
    info = StrategyInfo("bollinger_breakout", name, family="Momentum and breakout", holding_period="Swing",
                        summary="Buy a close above the upper band; sell a close below the middle band.", pine=True, **BB)

    def generate_signals(self, data):
        b = ta.bollinger(data["close"], self.p.window, self.p.k)
        return enter_exit(data["close"] > b["upper"], data["close"] < b["middle"])


class DipBuy(Strategy):
    name = "Dip buy after a losing streak"
    params = {"n_down": {"default": 3, "min": 1, "max": 10, "help": "Consecutive down closes"},
              "hold": {"default": 3, "min": 1, "max": 20, "help": "Bars to hold"}}
    info = StrategyInfo("dip_buy", name, family="Mean reversion", holding_period="Swing",
                        summary="The Lab 04 hypothesis as a strategy: buy after n down closes, hold for a few bars.",
                        how="Counts consecutive down closes; after the n-th it buys and holds for a fixed number of bars.",
                        rule="Streak >= n_down at the close: long for `hold` bars from the next open.",
                        works_best="Index ETFs with short-term overreaction and liquidity-provider flows.",
                        watch_out="Test the hypothesis first (Research > Hypothesis); falling knives in bear markets.",
                        course_ref="TOPIC 1 · A1", pine=False)

    def generate_signals(self, data):
        streak = ta.losing_streak(data["close"])
        return (streak >= self.p.n_down).astype(float).rolling(self.p.hold, min_periods=1).max()


# =========================================================================== breakout / momentum
class DonchianBreakout(Strategy):
    name = "Donchian channel breakout"
    params = {"entry": {"default": 20, "min": 5, "max": 200, "help": "Breakout lookback (bars)"},
              "exit": {"default": 10, "min": 2, "max": 200, "help": "Exit lookback (bars)"}}
    info = StrategyInfo("donchian_breakout", name, family="Momentum and breakout", holding_period="Position",
                        summary="Turtle-style breakout of the previous n-bar high; exit below the m-bar low.",
                        pine=True, **DC)

    def generate_signals(self, data):
        hi = data["high"].rolling(self.p.entry).max().shift(1)
        lo = data["low"].rolling(self.p.exit).min().shift(1)
        return enter_exit(data["close"] > hi, data["close"] < lo)


class TSMomentum(Strategy):
    name = "Time-series momentum"
    params = {"lookback": {"default": 126, "min": 5, "max": 504, "help": "Return lookback (bars)"},
              "threshold": {"default": 0.0, "min": -0.5, "max": 0.5, "step": 0.01},
              "allow_short": {"default": False, "help": "Short when past return is below -threshold"}}
    info = StrategyInfo("ts_momentum", name, family="Momentum and breakout", holding_period="Position",
                        summary="Long while the asset's own past return is positive (absolute momentum).",
                        how="Measures each asset's own trailing return over the lookback.",
                        rule="Past return > threshold: long; otherwise flat (or short if enabled).",
                        works_best="Persistent trends across months - futures CTAs and trend followers.",
                        watch_out="Late at turning points; whipsaw around zero; momentum crashes.",
                        course_ref="TOPIC 2 · K3", pine=True)

    def generate_signals(self, data):
        ret = data["close"].pct_change(self.p.lookback)
        sig = (ret > self.p.threshold).astype(float)
        if self.p.allow_short:
            sig = sig - (ret < -self.p.threshold).astype(float)
        return sig.where(ret.notna(), 0.0)


class XSMomentum(Strategy):
    name = "Cross-sectional momentum (multi-asset)"
    multi_asset = True
    params = {"lookback": {"default": 252, "min": 21, "max": 504, "help": "Ranking return lookback (bars)"},
              "skip": {"default": 21, "min": 0, "max": 63, "help": "Skip the most recent bars (12-1 momentum)"},
              "top_k": {"default": 3, "min": 1, "max": 10, "help": "Number of winners to hold"},
              "rebalance": {"default": 21, "min": 1, "max": 63, "help": "Bars between rebalances"},
              "long_short": {"default": False, "help": "Also short the bottom-ranked assets"}}
    info = StrategyInfo("xs_momentum", name, kind="portfolio", category="Factor and portfolio",
                        family="Momentum and breakout", holding_period="Position",
                        summary="Rank a universe by 12-1 month return each month, hold the top k equally weighted.",
                        default_symbols=["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "JPM", "XLF", "GLD", "TLT"], **XS)

    def generate_signals(self, data):
        closes = pd.DataFrame({s: d["close"] for s, d in data.items()}).dropna()
        mom = closes.shift(self.p.skip).pct_change(self.p.lookback - self.p.skip)
        w = pd.DataFrame(np.nan, index=closes.index, columns=closes.columns)
        k = min(self.p.top_k, len(closes.columns))
        for i in range(0, len(closes), self.p.rebalance):
            row = mom.iloc[i]
            if row.notna().sum() < k:
                continue
            rank = row.rank(ascending=False)
            wi = (rank <= k).astype(float) / k
            if self.p.long_short:
                wi = wi * 0.5 - (rank > len(row) - k).astype(float) / k * 0.5
            w.iloc[i] = wi.values
        return w.ffill().fillna(0.0)


# =========================================================================== statistical arbitrage
class PairsCointegration(Strategy):
    name = "Pairs trading (Engle-Granger z-score)"
    multi_asset = True
    allow_short = True
    params = {"formation": {"default": 756, "min": 120, "max": 2000, "help": "Bars used to estimate the hedge ratio"},
              "window": {"default": 60, "min": 10, "max": 252, "help": "Rolling window for the spread z-score"},
              "entry": {"default": 2.0, "min": 0.5, "max": 4.0, "step": 0.1, "help": "Enter when |z| exceeds"},
              "exit": {"default": 0.5, "min": 0.0, "max": 2.0, "step": 0.1, "help": "Exit when |z| falls below"}}
    info = StrategyInfo("pairs_cointegration", name, kind="portfolio", category="Statistical arbitrage and pairs",
                        family="Statistical / pairs arbitrage", holding_period="Swing", model_type="Statistical",
                        summary="Hedged, market-neutral spread trade: hedge ratio and ADF test on the formation period only.",
                        default_symbols=["KO", "PEP"], **PAIRS)

    def generate_signals(self, data):
        syms = list(data)[:2]
        if len(syms) < 2:
            raise ValueError("pairs trading needs two symbols, e.g. KO and PEP")
        a, b = syms
        closes = pd.DataFrame({s: data[s]["close"] for s in syms}).dropna()
        form = closes.iloc[: self.p.formation]
        alpha, beta, adf = PR.engle_granger(np.log(form[a]), np.log(form[b]))
        self.diagnostics = {"alpha": alpha, "beta": beta, "adf_t": adf, "cointegrated_5pct": adf < PR.EG_CRIT["5%"],
                            "half_life": PR.half_life(np.log(form[a]) - beta * np.log(form[b]) - alpha)}
        spread = np.log(closes[a]) - beta * np.log(closes[b]) - alpha
        z = (spread - spread.rolling(self.p.window).mean()) / spread.rolling(self.p.window).std()
        state = PR.spread_state(z, self.p.entry, self.p.exit)
        state.iloc[: self.p.formation] = 0.0                  # trade only after the formation period
        return PR.leg_weights(state, beta, a, b)


# =========================================================================== regime filter
class RegimeFiltered(Strategy):
    name = "Regime-filtered strategy (K-means gate)"
    params = {"base": {"default": "ema_cross", "choices": SIGNAL_BASES, "help": "Signal to gate"},
              "clusters": {"default": 3, "min": 2, "max": 5, "help": "Number of K-means regimes"},
              "min_train": {"default": 504, "min": 252, "max": 1500, "help": "Bars before the first regime fit"},
              "refit_every": {"default": 63, "min": 21, "max": 252, "help": "Bars between walk-forward refits"}}
    info = StrategyInfo("regime_filtered", name, model_type="Machine learning", family="Trend following",
                        summary="Walk-forward K-means regimes on volatility/trend features; the base signal is forced "
                                "flat in the high-volatility (stress) regime.", **KM)

    def generate_signals(self, data):
        base = REGISTRY[self.p.base]()
        tgt = base.run(data)
        feat = RG.regime_features(data["close"])
        labels = RG.walk_forward_regimes(feat, self.p.clusters, self.p.min_train, self.p.refit_every)
        self.regimes = labels
        gated = RG.regime_gate(tgt, labels)
        return gated.where(labels.reindex(tgt.index).notna(), 0.0)


# =========================================================================== machine learning
class _MLClassifier(Strategy):
    model = "logistic"
    params = {"threshold": {"default": 0.55, "min": 0.4, "max": 0.8, "step": 0.01, "help": "Go long when P(up) exceeds"},
              "min_train": {"default": 504, "min": 252, "max": 1500, "help": "Bars before the first fit"},
              "retrain_every": {"default": 126, "min": 21, "max": 504, "help": "Bars between walk-forward refits"}}

    def generate_signals(self, data):
        proba, folds = ML.walk_forward_proba(data, self.model, self.p.min_train, self.p.retrain_every)
        self.proba, self.folds = proba, folds
        return (proba > self.p.threshold).astype(float).where(proba.notna(), 0.0)


class MLLogistic(_MLClassifier):
    name = "ML: logistic regression (walk-forward)"
    model = "logistic"
    info = StrategyInfo("ml_logistic", name, model_type="Machine learning", family="Machine learning",
                        holding_period="Swing", summary="P(up tomorrow) from 14 leak-free features; long above threshold.",
                        **LR)


class MLRandomForest(_MLClassifier):
    name = "ML: random forest (walk-forward)"
    model = "random_forest"
    info = StrategyInfo("ml_random_forest", name, model_type="Machine learning", family="Machine learning",
                        holding_period="Swing", summary="Averaged decision trees on leak-free features, walk-forward.",
                        **RF)


class MLXGBoost(_MLClassifier):
    name = "ML: XGBoost (walk-forward)"
    model = "xgboost"
    info = StrategyInfo("ml_xgboost", name, model_type="Machine learning", family="Machine learning",
                        holding_period="Swing", summary="Gradient-boosted trees on leak-free features, walk-forward.",
                        **XG)


# =========================================================================== sentiment
class SentimentStrategy(Strategy):
    name = "News sentiment"
    params = {"window": {"default": 5, "min": 1, "max": 60, "help": "Days of sentiment to average"},
              "long_above": {"default": 0.05, "min": -1.0, "max": 1.0, "step": 0.01, "help": "Go long above this score"},
              "exit_below": {"default": -0.05, "min": -1.0, "max": 1.0, "step": 0.01, "help": "Exit below this score"},
              "trend_filter": {"default": True, "help": "Only long while close > SMA(200)"}}
    info = StrategyInfo("sentiment", name, family="Sentiment / NLP", holding_period="Swing", model_type="LLM and agentic",
                        summary="Rolling average of daily news sentiment (VADER lexicon or LLM) as a signal / filter.",
                        how="Scores each headline from -1 to +1 (VADER lexicon offline, optionally an LLM) and averages per day.",
                        rule="Rolling sentiment above the threshold: long; below the exit level: flat. Optional trend filter.",
                        works_best="News-driven names; as a filter on a technical signal rather than a stand-alone predictor.",
                        watch_out="Headline timing (published after the close?), sparse coverage, prompt injection in text. "
                                  "Offline demo sentiment is SYNTHETIC.",
                        course_ref="TOPIC 1 · K9", needs=["sentiment"], default_symbols=["NVDA"])

    def generate_signals(self, data):
        if "sentiment" not in data:
            raise ValueError("no sentiment column - load news first (Data > News & sentiment)")
        s = data["sentiment"].fillna(0.0).rolling(self.p.window, min_periods=1).mean()
        sig = enter_exit(s > self.p.long_above, s < self.p.exit_below)
        if self.p.trend_filter:
            m = ta.sma(data["close"], 200)
            sig = sig.where((data["close"] > m) | m.isna(), 0.0)
        return sig


# =========================================================================== agentic (rule brain, backtestable)
class AgenticDesk(Strategy):
    name = "Agentic multi-agent desk (rule brain)"
    params = {"buy_above": {"default": 0.25, "min": 0.0, "max": 1.0, "step": 0.05, "help": "Debate balance to buy"},
              "sell_below": {"default": -0.25, "min": -1.0, "max": 0.0, "step": 0.05, "help": "Debate balance to sell"},
              "news_weight": {"default": 0.4, "min": 0.0, "max": 1.0, "step": 0.05, "help": "Weight of the news analyst"}}
    info = StrategyInfo("agentic_desk", name, kind="agentic", model_type="LLM and agentic", family="Agentic AI",
                        holding_period="Swing",
                        summary="The analyst desk (technical + sentiment analysts, bull/bear debate, trader, risk manager) "
                                "replayed bar by bar with its deterministic rule brain so it can be backtested.",
                        how="Technical and sentiment analysts score the stock; bull and bear researchers debate; the "
                            "trader acts on the debate balance; the risk manager enforces hard limits.",
                        rule="Balance = (1 - w) x technical + w x news. Buy above the threshold, sell below.",
                        works_best="As a transparent baseline for the LLM desk (AI Agents page) - same roles, no LLM.",
                        watch_out="LLM agents cannot be backtested cheaply or reproducibly; hallucination and prompt "
                                  "injection; hard limits must stay outside the model.",
                        course_ref="TOPIC 1 · K1", needs=["sentiment"], default_symbols=["NVDA"])

    def generate_signals(self, data):
        c = data["close"]
        e20, e50, r = ta.ema(c, 20), ta.ema(c, 50), ta.rsi(c, 14)
        h = ta.macd(c)["hist"]
        tech = 0.4 * np.sign(e20 - e50) + 0.3 * np.sign(h) + 0.3 * ((r - 50) / 20).clip(-1, 1)
        tech = (tech - 0.3 * (r > 75)).clip(-1, 1)
        news = data["sentiment"].fillna(0.0).rolling(5, min_periods=1).mean() if "sentiment" in data else 0.0
        bal = (1 - self.p.news_weight) * tech + self.p.news_weight * news
        sig = enter_exit(bal > self.p.buy_above, bal < self.p.sell_below)
        return sig.where(e50.notna() & h.notna(), 0.0)


# =========================================================================== execution and market making
class _ExecutionAlgo(Strategy):
    algo = "vwap"
    params = {"qty": {"default": 50000, "min": 100, "max": 5_000_000, "help": "Parent order size (shares)"},
              "side": {"default": "buy", "choices": ["buy", "sell"]},
              "participation": {"default": 0.10, "min": 0.01, "max": 0.5, "step": 0.01, "help": "POV participation rate"},
              "impact_coef": {"default": 0.1, "min": 0.0, "max": 1.0, "step": 0.01, "help": "Square-root impact coefficient"}}

    def generate_signals(self, data):
        raise NotImplementedError("execution algorithms are simulated, not backtested as signals")


class ExecTWAP(_ExecutionAlgo):
    name = "Execution: TWAP"
    algo = "twap"
    info = StrategyInfo("exec_twap", name, kind="execution", category="Execution algorithms", family="Execution algorithms",
                        holding_period="Intraday", summary="Equal child orders per time slice over one session.",
                        needs=["intraday"], **EX)


class ExecVWAP(_ExecutionAlgo):
    name = "Execution: VWAP"
    algo = "vwap"
    info = StrategyInfo("exec_vwap", name, kind="execution", category="Execution algorithms", family="Execution algorithms",
                        holding_period="Intraday", summary="Child orders follow the historical intraday volume curve.",
                        needs=["intraday"], **EX)


class ExecPOV(_ExecutionAlgo):
    name = "Execution: POV (percentage of volume)"
    algo = "pov"
    info = StrategyInfo("exec_pov", name, kind="execution", category="Execution algorithms", family="Execution algorithms",
                        holding_period="Intraday", summary="Trade a fixed share of each bar's volume until filled.",
                        needs=["intraday"], **EX)


class MarketMaking(Strategy):
    name = "Market making (inventory skew)"
    params = {"half_spread_bps": {"default": 10.0, "min": 1.0, "max": 100.0, "help": "Quote distance from mid (bps)"},
              "clip": {"default": 100, "min": 1, "max": 10000, "help": "Shares per fill"},
              "max_inventory": {"default": 1000, "min": 10, "max": 100000, "help": "Inventory limit (shares)"},
              "skew_bps": {"default": 15.0, "min": 0.0, "max": 200.0, "help": "Quote skew at max inventory (bps)"}}
    info = StrategyInfo("market_making", name, kind="market_making", category="Market making", family="Market making",
                        holding_period="High-frequency", summary="Quote both sides around the mid, earn the spread, "
                        "skew quotes to shed inventory (simulated on hourly bars).", needs=["intraday"],
                        default_symbols=["SPY"], **MM)

    def generate_signals(self, data):
        res = mm.simulate(data, self.p.half_spread_bps, self.p.clip, self.p.max_inventory, self.p.skew_bps)
        return mm.signals_from_inventory(res["inventory"], self.p.max_inventory)


ALL = [BuyAndHold, SMACross, EMACross, TrendFilter, MACDCross, RSIThreshold, RSI2Reversion, BollingerReversion,
       BollingerBreakout, DipBuy, DonchianBreakout, TSMomentum, XSMomentum, PairsCointegration, RegimeFiltered,
       MLLogistic, MLRandomForest, MLXGBoost, SentimentStrategy, AgenticDesk, ExecTWAP, ExecVWAP, ExecPOV, MarketMaking]
REGISTRY: dict[str, type[Strategy]] = {cls.info.key: cls for cls in ALL}
