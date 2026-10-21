"""Idea -> strategy: turn a trading idea written in plain English into a validated strategy.

Learners do not write code. They describe the idea ("buy SPY when RSI(14) drops below 30,
sell above 70"); this module
  1. asks the connected AI brain (Codex / Claude / OpenAI - whatever AI_PROVIDER resolves to)
     to write the strategy against the plugin API, validates it in the sandbox (static checks,
     test run, look-ahead check) and lets the AI repair it once if validation fails;
  2. with no AI connected (or if the AI fails) falls back to a deterministic interpreter that
     recognises the common strategy families taught in the course and fills in the numbers.
Either way the result is ordinary plugin code the learner can read, save and backtest in one
click - the code is shown, never required.
"""
from __future__ import annotations

import re
import textwrap

from trader.agents import providers as AIP
from trader.config import get_settings

# --------------------------------------------------------------------------- AI author
SYSTEM = """You are a quant developer. Turn the user's trading idea into ONE Python strategy class for
this framework. Reply with a short bullet list (3-6 bullets, plain English, no code) explaining the
exact rules you implemented, then the code in a single ```python block. Nothing else.

Framework rules (follow exactly):
- Imports allowed: pandas as pd, numpy as np, math, statistics, scipy, sklearn,
  `from trader.core import indicators as ta`, `from trader.strategies.base import Strategy, enter_exit, flat_until_ready`.
  No other imports, no file/network access, no dunder attributes, no eval/exec.
- class X(Strategy): with class attributes `name = "..."` and `params = {"p": {"default": 20, "min": 2, "max": 200, "help": "..."}}`.
  Put every number from the idea in params so it can be tuned later. Read them as self.p.<name>.
- def generate_signals(self, data): data is a daily OHLCV DataFrame (columns open high low close volume,
  DatetimeIndex). Return a pd.Series aligned to data.index: 1 = long, 0 = flat (-1 = short only if the idea
  asks for shorting; then set `allow_short = True`).
- Use only information available at each bar (no shift(-1), no future data, no centred windows). The engine
  trades on the NEXT bar automatically - do not shift signals yourself.
- Helpers: ta.sma(s,n) ta.ema(s,n) ta.rsi(close,n) ta.macd(close,fast,slow,signal)->cols macd signal hist
  ta.bollinger(close,n,k)->cols middle upper lower  ta.atr(df,n)  ta.donchian(df,n)->cols upper lower middle
  ta.stochastic(df,k,d)  ta.realized_vol(close,n)  ta.losing_streak(close).
  enter_exit(entry_bool_series, exit_bool_series) -> stateful 1/0 position.
  flat_until_ready(cond, *indicator_series) -> 1.0 where cond, 0.0 during warm-up.
- Single asset only (no multi_asset). Keep it simple and readable for a beginner."""

_CODE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)


def _split(reply: str) -> tuple[list[str], str]:
    m = _CODE.search(reply or "")
    code = textwrap.dedent(m.group(1)).strip() + "\n" if m else ""
    head = (reply[:m.start()] if m else reply or "")
    bullets = [re.sub(r"^\s*[-*\d.)]+\s*", "", ln).strip() for ln in head.splitlines()]
    return [b for b in bullets if b][:8], code


def _ai_author(idea: str, validate) -> dict | None:
    provider = AIP.resolve()
    if isinstance(provider, AIP.RulesProvider) or provider.name == "rules":
        return None
    ok, _ = provider.available()
    if not ok:
        return None
    prompt = f"Trading idea:\n{idea.strip()}\n\nWrite the strategy."
    try:
        explain, code = _split(provider.complete(SYSTEM, prompt))
        if not code:
            return None
        v = validate(code)
        if not v["ok"]:                      # one repair round with the validator's messages
            issues = "; ".join(f"line {i.get('line')}: {i.get('message')}" for i in v["issues"])
            explain2, code2 = _split(provider.complete(
                SYSTEM, f"{prompt}\n\nYour previous code failed validation: {issues}\n\nPrevious code:\n```python\n{code}```\n"
                        "Fix it and reply in the same format."))
            if code2:
                explain, code, v = (explain2 or explain), code2, validate(code2)
        return {"code": code, "explanation": explain, "source": f"ai:{provider.name}", "validation": v}
    except Exception as exc:                 # fall back to the interpreter, but say why
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


# --------------------------------------------------------------------------- built-in interpreter
def _nums(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])", text)]


def _near(text: str, word: str, default: float, after: bool = True, span: int = 24) -> float:
    """First number within `span` characters after (or before) a keyword."""
    for m in re.finditer(word, text):
        window = text[m.end():m.end() + span] if after else text[max(0, m.start() - span):m.start()]
        n = _nums(window)
        if n:
            return n[0] if after else n[-1]
    return default


def _period(text: str, words: str, default: int) -> int:
    m = re.search(rf"(\d+)\s*-?\s*(?:day|bar|period|d)\s*(?:{words})", text) or \
        re.search(rf"(?:{words})\s*\(?\s*(\d+)", text)
    return int(m.group(1)) if m else default


def _klass(name: str) -> str:
    k = re.sub(r"[^A-Za-z0-9]", "", name.title())[:40] or "IdeaStrategy"
    return k if k[0].isalpha() else "Idea" + k          # a class name cannot start with a digit


def _render(name: str, doc: str, params: dict, body: str, extra_imports: str = "", short: bool = False) -> str:
    ptxt = ",\n".join(f'        "{k}": {{"default": {v[0]!r}, "min": {v[1]!r}, "max": {v[2]!r}, "help": "{v[3]}"}}'
                      for k, v in params.items())
    return (f"from trader.core import indicators as ta\n"
            f"from trader.strategies.base import Strategy, enter_exit, flat_until_ready\n{extra_imports}\n\n"
            f"class {_klass(name)}(Strategy):\n"
            f'    """{doc}"""\n'
            f'    name = "{name}"\n'
            + ("    allow_short = True\n" if short else "")
            + f"    params = {{\n{ptxt},\n    }}\n\n"
            f"    def generate_signals(self, data):\n"
            + textwrap.indent(textwrap.dedent(body).strip(), " " * 8) + "\n")


def interpret(idea: str) -> dict | None:
    """Recognise a course strategy family in plain English. Returns name/explanation/code or None."""
    t = " " + idea.lower().replace("-", " ") + " "
    short = bool(re.search(r"\bshort\b|\bsell short\b", t))

    if re.search(r"\brsi\b|relative strength", t):
        n = _period(t, r"rsi", 14)
        lo = _near(t, r"(below|under|less than|drops? to|oversold|<)", 30)
        hi = _near(t, r"(above|over|greater than|rises? to|overbought|>)", 70)
        lo, hi = (lo, hi) if lo < hi else (30, 70)
        return {"name": f"RSI({n}) reversion {int(lo)}-{int(hi)}",
                "explanation": [f"Compute the {n}-day RSI of the close.",
                                f"Buy when RSI falls below {lo:g} (oversold).",
                                f"Sell (go flat) when RSI rises above {hi:g} (overbought).",
                                "Orders are placed on the next bar's open by the backtest engine."],
                "code": _render(f"RSI({n}) reversion {int(lo)}-{int(hi)}",
                                f"Idea: {idea.strip()[:150]}",
                                {"period": (n, 2, 50, "RSI lookback"), "buy_below": (lo, 5, 50, "Buy when RSI is below"),
                                 "sell_above": (hi, 50, 95, "Sell when RSI is above")},
                                """
                                r = ta.rsi(data["close"], self.p.period)
                                return enter_exit(r < self.p.buy_below, r > self.p.sell_above)
                                """)}

    if "macd" in t:
        return {"name": "MACD crossover",
                "explanation": ["Compute MACD(12, 26) and its 9-day signal line.",
                                "Be long while the MACD line is above the signal line.",
                                "Short while it is below." if short else "Go flat when it crosses back below."],
                "code": _render("MACD crossover", f"Idea: {idea.strip()[:150]}",
                                {"fast": (12, 2, 50, "Fast EMA"), "slow": (26, 5, 100, "Slow EMA"),
                                 "signal": (9, 2, 30, "Signal EMA")},
                                f"""
                                m = ta.macd(data["close"], self.p.fast, self.p.slow, self.p.signal)
                                up = (m["macd"] > m["signal"]).astype(float)
                                return {'up * 2 - 1' if short else 'up'}
                                """, short=short)}

    if re.search(r"bollinger|\bbands?\b", t):
        n = _period(t, r"bollinger|band", 20)
        k = _near(t, r"(std|standard deviation|sigma)", 2.0, after=False) or 2.0
        to_upper = "upper" in t and re.search(r"(sell|exit|close).{0,30}upper", t)
        return {"name": f"Bollinger({n}) mean reversion",
                "explanation": [f"Build {n}-day Bollinger Bands at {k:g} standard deviations.",
                                "Buy when the close drops below the lower band.",
                                "Sell when the close reaches the " + ("upper band." if to_upper else "middle band (the average).")],
                "code": _render(f"Bollinger({n}) mean reversion", f"Idea: {idea.strip()[:150]}",
                                {"window": (n, 5, 100, "Band lookback"), "k": (k, 0.5, 4.0, "Band width in std devs")},
                                f"""
                                b = ta.bollinger(data["close"], self.p.window, self.p.k)
                                return enter_exit(data["close"] < b["lower"], data["close"] > b["{'upper' if to_upper else 'middle'}"])
                                """)}

    if re.search(r"break ?out|new high|\d+ ?day high|donchian|channel|highest", t):
        n = _period(t, r"high|breakout|channel|donchian", 20)
        m = _period(t, r"low", max(5, n // 2))
        return {"name": f"{n}-day breakout",
                "explanation": [f"Buy when the close breaks above the highest high of the previous {n} days.",
                                f"Sell when the close falls below the lowest low of the previous {m} days."],
                "code": _render(f"{n}-day breakout", f"Idea: {idea.strip()[:150]}",
                                {"entry_days": (n, 5, 250, "Breakout lookback"), "exit_days": (m, 2, 250, "Exit lookback")},
                                """
                                hi = data["high"].rolling(self.p.entry_days).max().shift(1)
                                lo = data["low"].rolling(self.p.exit_days).min().shift(1)
                                return enter_exit(data["close"] > hi, data["close"] < lo)
                                """)}

    if re.search(r"down days?|losing streak|in a row|consecutive|dip", t):
        n = int(_near(t, r"(after|following)", 3)) if re.search(r"after|following", t) else 3
        n = n if 1 <= n <= 10 else 3
        hold = int(_near(t, r"(hold|for|keep)", 5))
        hold = hold if 1 <= hold <= 60 else 5
        return {"name": f"Buy the dip after {n} down days",
                "explanation": ["Count consecutive down closes.",
                                f"Buy after {n} down days in a row.",
                                f"Hold for {hold} trading days, then sell."],
                "code": _render(f"Buy the dip after {n} down days", f"Idea: {idea.strip()[:150]}",
                                {"streak": (n, 1, 10, "Down days in a row"), "hold_days": (hold, 1, 60, "Days to hold")},
                                """
                                entry = ta.losing_streak(data["close"]) >= self.p.streak
                                return entry.astype(float).rolling(self.p.hold_days, min_periods=1).max()
                                """)}

    if re.search(r"golden cross|death cross|moving average|\bsma\b|\bema\b|\bma\b|cross(es|ing)? (over|above)", t):
        ema = bool(re.search(r"\bema\b|exponential", t))
        nums = [int(x) for x in _nums(t) if 2 <= x <= 400]
        fast, slow = (sorted(nums[:2]) if len(nums) >= 2 else (50, 200) if "golden" in t or "death" in t else (20, 50))
        kind = "EMA" if ema else "SMA"
        f = "ema" if ema else "sma"
        return {"name": f"{kind} {fast}/{slow} crossover",
                "explanation": [f"Compute the {fast}-day and {slow}-day {kind} of the close.",
                                f"Be long while the {fast}-day average is above the {slow}-day average.",
                                "Short while it is below." if short else "Go flat when it crosses back below."],
                "code": _render(f"{kind} {fast}/{slow} crossover", f"Idea: {idea.strip()[:150]}",
                                {"fast": (fast, 2, 200, f"Fast {kind}"), "slow": (slow, 5, 400, f"Slow {kind}")},
                                f"""
                                a, b = ta.{f}(data["close"], self.p.fast), ta.{f}(data["close"], self.p.slow)
                                up = flat_until_ready(a > b, a, b)
                                return {'up * 2 - 1' if short else 'up'}
                                """, short=short)}

    if re.search(r"momentum|trend|went up|is up|rising|positive return|return.{0,25}positive|past \d+", t):
        mo = re.search(r"(\d+)\s*months?", t)
        n = (int(mo.group(1)) * 21 if mo and not re.search(r"\d+\s*(?:day|d)\b", t) else 0) or \
            _period(t, r"return|momentum|trend", 0) or int(_near(t, r"(past|last|over)", 126))
        n = n if 5 <= n <= 504 else 126
        return {"name": f"{n}-day time-series momentum",
                "explanation": [f"Measure the return over the past {n} trading days.",
                                "Be long when that return is positive.",
                                "Short when it is negative." if short else "Go flat when it is negative."],
                "code": _render(f"{n}-day time-series momentum", f"Idea: {idea.strip()[:150]}",
                                {"lookback": (n, 5, 504, "Momentum lookback (days)")},
                                f"""
                                ret = data["close"].pct_change(self.p.lookback)
                                up = flat_until_ready(ret > 0, ret)
                                return {'up * 2 - 1' if short else 'up'}
                                """, short=short)}
    return None


EXAMPLES = [
    "Buy when the 50-day moving average crosses above the 200-day, sell when it crosses below",
    "Buy when RSI(14) drops below 30 and sell when it rises above 70",
    "Buy when the close falls below the lower Bollinger Band, sell at the middle band",
    "Buy a breakout above the 20-day high, sell below the 10-day low",
    "Buy SPY after 3 down days in a row and hold for 5 days",
    "Be long when MACD is above its signal line",
    "Go long when the 6-month (126-day) return is positive",
]


def generate(idea: str, validate, use_ai: bool = True) -> dict:
    """Plain-English idea -> {name, explanation, code, source, validation, note}."""
    idea = (idea or "").strip()
    if len(idea) < 8:
        return {"ok": False, "message": "Describe your idea in a sentence, e.g. " + EXAMPLES[1]}
    note = ""
    if use_ai and get_settings().ai_provider != "rules":
        out = _ai_author(idea, validate)
        if out and "code" in out and out["validation"]["ok"]:
            return {"ok": True, **out, "note": ""}
        note = ("The AI's code did not pass validation, so the built-in interpreter was used."
                if out and "code" in out else
                f"The AI was not reachable ({out['error']}), so the built-in interpreter was used."
                if out and "error" in out else "")
    rec = interpret(idea)
    if not rec:
        return {"ok": False, "message": "I could not recognise that idea without an AI connected. Connect OpenAI Codex "
                                        "(ChatGPT sign-in) or an API key on the Integrations page, or start from one of "
                                        "the examples: moving-average crossover, RSI, Bollinger Bands, breakout, "
                                        "buy-the-dip, MACD or momentum.", "examples": EXAMPLES}
    v = validate(rec["code"])
    return {"ok": v["ok"], "name": rec["name"], "explanation": rec["explanation"], "code": rec["code"],
            "source": "built-in interpreter", "validation": v, "note": note}
