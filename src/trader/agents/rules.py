"""Deterministic rule-based brain for every desk role (works offline, no AI login needed)."""
from __future__ import annotations


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, float(x)))


def technical_analyst(ctx: dict, reports: dict) -> dict:
    t = ctx["technical"]
    up = t["ema20"] > t["ema50"]
    score = 0.4 * (1 if up else -1) + 0.3 * (1 if t["macd_hist"] > 0 else -1) + 0.3 * _clip((t["rsi14"] - 50) / 20)
    sig = [f"{'Up' if up else 'Down'}trend: EMA20 {t['ema20']} {'>' if up else '<'} EMA50 {t['ema50']}",
           f"MACD histogram {'positive' if t['macd_hist'] > 0 else 'negative'} ({t['macd_hist']})", f"RSI(14) {t['rsi14']}"]
    if t["rsi14"] > 75:
        score -= 0.3
        sig.append("RSI above 75 - stretched, momentum may be exhausted")
    return {"score": round(_clip(score), 2), "summary": f"{'Up' if up else 'Down'}trend, RSI {t['rsi14']:.0f}, MACD "
            f"{'positive' if t['macd_hist'] > 0 else 'negative'}", "signals": sig}


def sentiment_analyst(ctx: dict, reports: dict) -> dict:
    items = ctx["news"]
    if not items:
        return {"score": 0.0, "summary": "No headlines - neutral", "events": []}
    s = sum(i["lexicon_score"] for i in items) / len(items)
    events = [i["headline"] for i in items if any(w in i["headline"].lower() for w in
                                                  ("probe", "lawsuit", "restriction", "downgrade", "upgrade", "guidance", "earnings"))]
    syn = " (SYNTHETIC demo headlines)" if any(i.get("synthetic") for i in items) else ""
    return {"score": round(_clip(s), 2), "summary": f"{len(items)} headlines, average lexicon sentiment {s:+.2f}{syn}",
            "events": events[:4]}


def fundamental_analyst(ctx: dict, reports: dict) -> dict:
    f = ctx["fundamentals"]
    score = _clip(f["ret_1y"] * 1.5) * 0.4 + (0.3 if f["drawdown_from_high"] > -0.10 else -0.3) + \
        (0.3 if f["vol_1y"] < 0.30 else -0.2)
    risks = []
    if f["vol_1y"] > 0.35:
        risks.append(f"high volatility {f['vol_1y']:.0%}")
    if (f["beta_spy"] or 0) > 1.3:
        risks.append(f"high beta {f['beta_spy']}")
    if f["drawdown_from_high"] < -0.15:
        risks.append(f"{f['drawdown_from_high']:.0%} below its 52-week high")
    return {"score": round(_clip(score), 2), "summary": f"{f['sector']}: 1y return {f['ret_1y']:+.0%}, vol {f['vol_1y']:.0%}, "
            f"beta {f['beta_spy']}", "risks": risks or ["no major risk flags (price-derived view only)"]}


def _balance(reports: dict) -> float:
    t = reports["technical_analyst"]["score"]
    n = reports["sentiment_analyst"]["score"]
    f = reports["fundamental_analyst"]["score"]
    return 0.5 * t + 0.3 * n + 0.2 * f


def bull_researcher(ctx: dict, reports: dict) -> dict:
    pts = []
    for k in ("technical_analyst", "sentiment_analyst", "fundamental_analyst"):
        r = reports[k]
        if r["score"] > 0:
            pts.append(f"{k.replace('_', ' ').title()}: {r['summary']} (score {r['score']:+.2f})")
    if ctx["technical"]["rsi14"] < 35:
        pts.append(f"RSI {ctx['technical']['rsi14']} is oversold - rebound potential")
    if reports.get("bear_researcher"):
        pts.append("Rebuttal: the bear's points are already priced in if the trend holds")
    b = _balance(reports)
    return {"points": pts or ["No strong bullish evidence"], "conviction": round(max(0.0, min(1.0, 0.5 + b / 2)), 2)}


def bear_researcher(ctx: dict, reports: dict) -> dict:
    pts = []
    for k in ("technical_analyst", "sentiment_analyst", "fundamental_analyst"):
        r = reports[k]
        if r["score"] < 0:
            pts.append(f"{k.replace('_', ' ').title()}: {r['summary']} (score {r['score']:+.2f})")
    if ctx["technical"]["rsi14"] > 70:
        pts.append(f"RSI {ctx['technical']['rsi14']} is overbought - pullback risk")
    pts += [f"Risk flag: {x}" for x in reports["fundamental_analyst"].get("risks", []) if "no major" not in x]
    if reports.get("bull_researcher"):
        pts.append("Rebuttal: trend signals lag; a reversal would hit before the bull case adjusts")
    b = _balance(reports)
    return {"points": pts or ["No strong bearish evidence"], "conviction": round(max(0.0, min(1.0, 0.5 - b / 2)), 2)}


def trader(ctx: dict, reports: dict) -> dict:
    bal = _balance(reports)
    debate = reports["bull_researcher"]["conviction"] - reports["bear_researcher"]["conviction"]
    b = 0.6 * bal + 0.4 * debate
    held = ctx["position"]["qty"]
    action = "buy" if b > 0.25 and held <= 0 else "sell" if b < -0.25 and held > 0 else "hold"
    conf = round(min(1.0, abs(b) + 0.3), 2)
    return {"action": action, "confidence": conf, "size_pct": round(0.25 * conf, 3) if action == "buy" else 0.0,
            "rationale": f"Desk balance {b:+.2f} (analysts {bal:+.2f}, debate {debate:+.2f}) -> {action}"}


def risk_manager(ctx: dict, reports: dict) -> dict:
    p = reports["trader"]
    t = ctx["technical"]
    notes = []
    size = float(p.get("size_pct", 0) or 0)
    decision = "approve"
    if p["action"] == "hold":
        return {"decision": "approve", "size_pct": 0.0, "stop_atr": 2.0, "target_atr": 3.0, "notes": ["nothing to do"]}
    vol = ctx["fundamentals"]["vol_1y"]
    if vol > 0.45 and size > 0.10:
        size, decision = 0.10, "resize"
        notes.append(f"volatility {vol:.0%} - size cut to 10%")
    if p["confidence"] < 0.6 and p["action"] == "buy":
        decision = "reject"
        notes.append(f"confidence {p['confidence']} below 0.6")
    notes.append(f"ATR(14) {t['atr14']}: stop 2 x ATR, target 3 x ATR")
    return {"decision": decision, "size_pct": round(size, 3), "stop_atr": 2.0, "target_atr": 3.0, "notes": notes}


def portfolio_manager(ctx: dict, reports: dict) -> dict:
    gate = reports.get("risk_limits", {})
    p = reports["trader"]
    if p["action"] == "hold":
        return {"decision": "hold", "summary": "No trade: the desk's balance is inside the no-trade band.", "watch": []}
    if gate.get("decision") != "APPROVED":
        return {"decision": "reject", "summary": f"Blocked by the hard risk limits: {'; '.join(gate.get('notes', []))}",
                "watch": []}
    return {"decision": "approve", "summary": f"{p['action'].upper()} {gate.get('qty')} {ctx['symbol']}: {p['rationale']}. "
            "Sent to the human for approval.", "watch": reports["bear_researcher"]["points"][:2]}


BRAINS = {"technical_analyst": technical_analyst, "sentiment_analyst": sentiment_analyst,
          "fundamental_analyst": fundamental_analyst, "bull_researcher": bull_researcher,
          "bear_researcher": bear_researcher, "trader": trader, "risk_manager": risk_manager,
          "portfolio_manager": portfolio_manager}
