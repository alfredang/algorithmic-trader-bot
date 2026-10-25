"""Deterministic rule-based brain for every agent (works offline, no AI login needed).

Each function takes the agent's context and the reports so far and returns the agent's JSON. The LLM
providers return the same JSON shape; the workflow sanitises it and falls back to these brains on errors.
"""
from __future__ import annotations

import math

from trader.agents import algorithms as ALG
from trader.agents.roles import ALGORITHMS, DEFAULT_GUIDANCE

EVENT_WORDS = ("probe", "lawsuit", "restriction", "downgrade", "upgrade", "guidance", "earnings", "recall", "sec ",
               "investigation", "beat", "miss", "short", "squeeze", "acquisition", "merger")


def _clip(x, lo=-1.0, hi=1.0):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) else max(lo, min(hi, v))


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:+.1%}"


# --------------------------------------------------------------------------- 1. lead
def lead(ctx: dict, reports: dict) -> dict:
    g = ctx.get("guidance") or DEFAULT_GUIDANCE
    syms = ", ".join(ctx.get("symbols") or [])
    if ctx.get("phase") != "summary":
        top = sorted(g["weights"].items(), key=lambda kv: -kv[1])[:3]
        return {"plan": [f"Finance Research and News Sentiment in parallel for {syms} ({ctx.get('mode', 'auto')} data)",
                         "Trading Strategy: weights from the latest review - " + ", ".join(f"{k} {v:.0%}" for k, v in top),
                         f"Signal Generation: long above {g['long_above']:+.2f}, short below {g['short_below']:+.2f}",
                         f"Stock Trader: market orders of {ctx.get('position_pct', 0.1):.0%} of equity on the "
                         f"{ctx.get('account', 'paper')} account",
                         "Performance Analysis and Strategy Review, then the new guidance feeds the next run"],
                "focus": (g.get("notes") or [g.get("summary", "")])[0][:200], "summary": ""}
    parts = []
    for sym, r in (ctx.get("results") or {}).items():
        sig = (r.get("signal_generation") or {}).get("signal")
        tr = r.get("stock_trader") or {}
        parts.append(f"{sym} {sig or 'null'} -> {tr.get('action', 'none')}")
    m = ctx.get("metrics") or {}
    rv = ctx.get("review") or {}
    return {"summary": (f"Signals: {'; '.join(parts) or 'none'}. Agent account return {_pct(m.get('total_return'))}, "
                        f"max drawdown {_pct(m.get('max_drawdown'))}, {m.get('trades', 0)} trade(s). "
                        f"Review: {rv.get('summary', 'guidance unchanged')}")[:600]}


# --------------------------------------------------------------------------- 2. finance research
def finance_research(ctx: dict, reports: dict) -> dict:
    f = ctx["finance"]
    per = (ctx.get("votes") or {}).get("per_interval") or {}
    trend = [per[iv]["trend"]["score"] for iv in per]
    price = sum(trend) / len(trend) if trend else 0.0
    rp = f["risk_profile"]
    risk = _clip(rp["ret_1y"] * 1.5) * 0.4 + (0.3 if rp["drawdown_from_high"] > -0.10 else -0.3) + \
        (0.3 if rp["vol_1y"] < 0.30 else -0.2)
    highlights, risks = [], []
    for iv, snap in f["intervals"].items():
        highlights.append(f"{iv}: close {snap['close']}, {snap['trend']}trend, RSI {snap['rsi14']}, 20-bar {_pct(snap['ret_20bars'])}")
    prof = (f.get("yahoo") or {}).get("profile") or {}
    fund, have_fund = 0.0, bool(prof)
    if have_fund:
        g = prof.get("revenueGrowth")
        if g is not None:
            fund += 0.3 if g > 0 else -0.3
            (highlights if g > 0 else risks).append(f"revenue growth {g:+.1%}")
        pm = prof.get("profitMargins")
        if pm is not None:
            fund += 0.2 if pm > 0.10 else -0.1
            highlights.append(f"profit margin {pm:.1%}")
        tpe, fpe = prof.get("trailingPE"), prof.get("forwardPE")
        if tpe and fpe:
            fund += 0.2 if fpe < tpe else -0.1
            highlights.append(f"P/E {tpe:.1f} trailing vs {fpe:.1f} forward")
        if (prof.get("debtToEquity") or 0) > 200:
            fund -= 0.2
            risks.append(f"debt/equity {prof['debtToEquity']:.0f}%")
        rec = prof.get("recommendationKey")
        if rec:
            fund += 0.2 if rec in ("buy", "strong_buy") else -0.2 if rec in ("sell", "strong_sell", "underperform") else 0.0
            highlights.append(f"analyst consensus: {rec}")
        fund = _clip(fund)
    eq = f.get("equibles") or {}
    if eq.get("available"):
        highlights.append("Equibles company data available (valuation, short interest, insiders, ownership)")
    if rp["vol_1y"] > 0.35:
        risks.append(f"high volatility {rp['vol_1y']:.0%}")
    if (rp["beta_spy"] or 0) > 1.3:
        risks.append(f"high beta {rp['beta_spy']}")
    if rp["drawdown_from_high"] < -0.15:
        risks.append(f"{rp['drawdown_from_high']:.0%} below its 52-week high")
    missing = [k for k, v in f["candle_sources"].items() if v.get("error")]
    if missing:
        risks.append(f"no {', '.join(missing)} candles ({f['candle_sources'][missing[0]]['error'][:80]})")
    if not have_fund:
        risks.append("no Yahoo Finance fundamentals (" + ((f.get("yahoo") or {}).get("note") or
                                                          (f.get("yahoo") or {}).get("error") or "unavailable")[:80] + ")")
    score = 0.45 * price + 0.25 * risk + 0.30 * fund if have_fund else 0.6 * price + 0.4 * risk
    return {"score": round(_clip(score), 2),
            "summary": f"{f.get('company') or ctx['symbol']} ({rp['sector']}): price trend {price:+.2f} over "
                       f"{len(trend)} interval(s), 1y return {_pct(rp['ret_1y'])}, vol {rp['vol_1y']:.0%}"
                       + (f", fundamentals {fund:+.2f}" if have_fund else ", price-derived view only"),
            "highlights": highlights[:8], "risks": risks[:6] or ["no major risk flags"],
            "data": {"intervals": {iv: {k: s[k] for k in ("bars", "last", "close", "trend", "rsi14", "atr14", "ret_20bars")}
                                   for iv, s in f["intervals"].items()},
                     "sources": {"candles": f["candle_sources"],
                                 "yahoo": "ok" if have_fund else ((f.get("yahoo") or {}).get("error") or (f.get("yahoo") or {}).get("note")),
                                 "equibles": "ok" if eq.get("available") else (eq.get("error") or eq.get("note"))},
                     "fundamentals": {k: prof[k] for k in ("marketCap", "trailingPE", "forwardPE", "priceToBook", "profitMargins",
                                                           "revenueGrowth", "debtToEquity", "beta", "recommendationKey") if k in prof},
                     "risk_profile": rp}}


# --------------------------------------------------------------------------- 3. news sentiment
def news_sentiment(ctx: dict, reports: dict) -> dict:
    rd, nw = ctx["sentiment"]["reddit"], ctx["sentiment"]["newsapi"]
    r, n = rd.get("lexicon_score", 0.0), nw.get("lexicon_score", 0.0)
    if rd.get("n") and nw.get("n"):
        overall = 0.4 * r + 0.6 * n
    elif rd.get("n"):
        overall = r
    else:
        overall = n if nw.get("n") else 0.0
    posts = sorted(rd.get("posts") or [], key=lambda p: -p.get("upvotes", 0))
    heads = nw.get("items") or []
    events = [h["headline"] for h in heads if any(w in h["headline"].lower() for w in EVENT_WORDS)]
    loud = [h["headline"] for h in sorted(heads, key=lambda h: -abs(h["lexicon_score"]))]
    syn = " (SYNTHETIC demo headlines)" if nw.get("synthetic") else ""
    rtxt = f"Reddit {r:+.2f} over {rd['n']} post(s)" if rd.get("n") else \
        "no Reddit posts (" + (rd.get("note") or rd.get("error") or "none found")[:60] + ")"
    return {"score": round(_clip(overall), 2),
            "summary": f"{rtxt}; headlines {n:+.2f} over {nw.get('n', 0)} item(s){syn}.",
            "notable": {"reddit": [f"r/{p['subreddit']}: {p['title'][:140]} ({p['upvotes']} upvotes)" for p in posts[:3]],
                        "newsapi": list(dict.fromkeys(events + loud))[:4]},
            "lexicon": {"overall": round(overall, 3), "reddit": {"score": r, "n": rd.get("n", 0)},
                        "newsapi": {"score": n, "n": nw.get("n", 0), "source": nw.get("source"),
                                    "synthetic": nw.get("synthetic", False)}}}


# --------------------------------------------------------------------------- 4. trading strategy
def trading_strategy(ctx: dict, reports: dict) -> dict:
    g = ctx.get("guidance") or DEFAULT_GUIDANCE
    w = ALG.normalise_weights(g.get("weights"), DEFAULT_GUIDANCE["weights"])
    comb = (ctx.get("votes") or {}).get("combined") or {}
    chosen = [k for k, v in sorted(w.items(), key=lambda kv: -kv[1]) if v >= 0.1]
    mode = "single" if max(w.values()) >= 0.5 else "mix"
    contrib = sorted(((k, w[k] * comb.get(k, {}).get("score", 0.0)) for k in w), key=lambda kv: -abs(kv[1]))
    return {"mode": mode, "algorithms": chosen, "weights": w, "sentiment_weight": g.get("sentiment_weight", 0.2),
            "finance_weight": g.get("finance_weight", 0.15),
            "rationale": f"{mode.title()} of {', '.join(chosen)} per the latest review; largest contributions: "
                         + ", ".join(f"{k} {c:+.2f}" for k, c in contrib[:3]) + "."}


# --------------------------------------------------------------------------- 5. signal generation
def signal_generation(ctx: dict, reports: dict) -> dict:
    g = ctx.get("guidance") or DEFAULT_GUIDANCE
    comp = (reports.get("trading_strategy") or {}).get("composite", {}).get("composite", 0.0)
    la, sb = g["long_above"], g["short_below"]
    sig = "long" if comp > la else "short" if comp < sb else None
    if sig:
        conf = min(1.0, 0.5 + (abs(comp) - (la if sig == "long" else -sb)) * 1.5)
    else:
        conf = 0.5 + 0.4 * (1 - min(1.0, abs(comp) / max(la if comp >= 0 else -sb, 1e-6)))
    return {"signal": sig, "confidence": round(_clip(conf, 0, 1), 2),
            "rationale": f"Composite {comp:+.2f} vs long above {la:+.2f} / short below {sb:+.2f} -> {sig or 'null (no trade)'}"}


# --------------------------------------------------------------------------- 6. stock trader (deterministic plan)
def plan_trade(signal: str | None, held: float, price: float, equity: float, position_pct: float) -> dict:
    """Order legs for a signal: long -> buy, short -> sell short; an opposite position is closed first."""
    target = math.floor(equity * position_pct / price) if price > 0 else 0
    legs, notes = [], []
    if signal is None:
        return {"action": "none", "legs": [], "target_qty": 0, "notes": ["signal null - no order"]}
    want = 1 if signal == "long" else -1
    if held * want < 0:                                   # opposite position: close it first
        legs.append({"side": "buy" if held < 0 else "sell", "qty": abs(held), "purpose": "close"})
        notes.append(f"close the {'short' if held < 0 else 'long'} {abs(held):g} first")
        held = 0.0
    if held * want > 0:
        notes.append(f"already {signal} {abs(held):g} shares - no new order")
        return {"action": "hold", "legs": [], "target_qty": target, "notes": notes}
    if target < 1:
        notes.append(f"{position_pct:.0%} of equity buys less than one share at {price:.2f}")
        return {"action": "cover" if legs and want > 0 else "sell" if legs else "none", "legs": legs, "target_qty": 0,
                "notes": notes}
    legs.append({"side": "buy" if want > 0 else "sell", "qty": float(target), "purpose": "open"})
    notes.append(f"{'buy' if want > 0 else 'sell short'} {target} shares = {position_pct:.0%} of equity {equity:,.0f} at ~{price:.2f}")
    return {"action": "buy" if want > 0 else "short", "legs": legs, "target_qty": target, "notes": notes}


def stock_trader(ctx: dict, reports: dict) -> dict:
    sig = (reports.get("signal_generation") or {}).get("signal")
    p = plan_trade(sig, ctx["position"]["qty"], ctx["price"], ctx["position"]["equity"], ctx["sizing"]["position_pct"])
    return {"action": p["action"], "orders": [], "notes": p["notes"]}


# --------------------------------------------------------------------------- 7. performance analysis
def performance_analysis(ctx: dict, reports: dict) -> dict:
    m = ctx.get("metrics") or {}
    obs = []
    if m.get("sharpe") is None:
        obs.append(f"Sharpe needs at least two trading days of equity history ({m.get('days', 0)} so far)")
    else:
        obs.append(f"Sharpe {m['sharpe']:.2f} on {m.get('days')} day(s) of history")
    if m.get("round_trips"):
        obs.append(f"win rate {m['win_rate']:.0%} over {m['round_trips']} closed round trip(s)")
    else:
        obs.append("no closed round trips yet - win rate undefined")
    obs.append(f"exposure {(m.get('exposure') or 0):.0%} of snapshots, gross exposure {(m.get('gross_exposure') or 0):.0%} of equity")
    if m.get("orders_rejected"):
        obs.append(f"{m['orders_rejected']} order(s) rejected by the broker")
    return {"summary": f"Agent account equity {m.get('equity', 0):,.2f} ({_pct(m.get('total_return'))} total, max drawdown "
                       f"{_pct(m.get('max_drawdown'))}) after {m.get('trades', 0)} fill(s) and {m.get('orders', 0)} order(s).",
            "observations": obs}


# --------------------------------------------------------------------------- 8. strategy review
def hit_rates(recent: list[dict], min_obs: int = 2) -> dict:
    """Share of past non-zero votes whose sign matched the later price move, per algorithm (+ sentiment, finance)."""
    stats: dict[str, list[int]] = {}
    for s in recent:
        ret = s.get("ret")
        if ret is None or abs(ret) < 5e-4:
            continue
        for k, v in {**(s.get("votes") or {}), "sentiment": s.get("sentiment"), "finance": s.get("finance")}.items():
            if v is None or abs(v) <= ALG.DEAD_BAND:
                continue
            stats.setdefault(k, []).append(int((v > 0) == (ret > 0)))
    return {k: {"hit_rate": round(sum(v) / len(v), 3), "n": len(v)} for k, v in stats.items() if len(v) >= min_obs}


def strategy_review(ctx: dict, reports: dict) -> dict:
    g = ctx.get("guidance") or DEFAULT_GUIDANCE
    m = ctx.get("metrics") or {}
    hr = hit_rates(ctx.get("recent_signals") or [])
    w = dict(ALG.normalise_weights(g.get("weights"), DEFAULT_GUIDANCE["weights"]))
    notes = []
    for k in ALGORITHMS:
        if k in hr:
            w[k] = w.get(k, 0.0) * (0.5 + hr[k]["hit_rate"])
            notes.append(f"{k}: {hr[k]['hit_rate']:.0%} of {hr[k]['n']} past votes right")
    w = {k: 0.8 * w.get(k, 0.0) + 0.2 * DEFAULT_GUIDANCE["weights"][k] for k in ALGORITHMS}      # shrink to the default
    w = ALG.normalise_weights(w)
    la, sb = g["long_above"], g["short_below"]
    sharpe, mdd = m.get("sharpe"), m.get("max_drawdown")
    if (sharpe is not None and sharpe < 0) or (mdd is not None and mdd < -0.05):
        la, sb = la + 0.05, sb - 0.05
        notes.append("losing or drawing down - raise the thresholds (trade less, only strong signals)")
    elif m.get("round_trips", 0) >= 3 and (m.get("win_rate") or 0) >= 0.55:
        la, sb = la - 0.02, sb + 0.02
        notes.append("win rate above 55% - lower the thresholds slightly")
    sw, fw = g.get("sentiment_weight", 0.2), g.get("finance_weight", 0.15)
    if "sentiment" in hr:
        sw += 0.03 if hr["sentiment"]["hit_rate"] > 0.55 else -0.03 if hr["sentiment"]["hit_rate"] < 0.45 else 0.0
    if "finance" in hr:
        fw += 0.03 if hr["finance"]["hit_rate"] > 0.55 else -0.03 if hr["finance"]["hit_rate"] < 0.45 else 0.0
    if not hr:
        notes.append("not enough evaluated signals yet (the price has to move after a signal) - weights kept near the default")
    preferred = [k for k, _ in sorted(w.items(), key=lambda kv: -kv[1])[:3]]
    return {"weights": w, "long_above": round(_clip(la, 0.05, 0.8), 3), "short_below": round(_clip(sb, -0.8, -0.05), 3),
            "sentiment_weight": round(_clip(sw, 0, 0.5), 3), "finance_weight": round(_clip(fw, 0, 0.5), 3),
            "preferred_algorithms": preferred, "notes": notes[:8],
            "summary": f"Prefer {', '.join(preferred)}; long above {_clip(la, 0.05, 0.8):+.2f}, short below {_clip(sb, -0.8, -0.05):+.2f}.",
            "hit_rates": hr}


BRAINS = {"lead": lead, "finance_research": finance_research, "news_sentiment": news_sentiment,
          "trading_strategy": trading_strategy, "signal_generation": signal_generation, "stock_trader": stock_trader,
          "performance_analysis": performance_analysis, "strategy_review": strategy_review}
