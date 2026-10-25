"""The 8-agent workflow, offline: rule brains or a mocked LLM, demo data, the simulator broker - no network."""
import math
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import delete, select

from trader.agents import algorithms as ALG
from trader.agents import performance as PERF
from trader.agents import rules as RULES
from trader.agents import workflow as WF
from trader.agents.providers import Provider, parse_json, parse_openai_items
from trader.agents.roles import ALGORITHMS, DEFAULT_GUIDANCE, ROLE_ORDER, SYMBOL_AGENTS
from trader.broker import service as BRK
from trader.models import Order, Position, Setting

CANNED = {
    "lead": {"plan": ["research", "trade"], "focus": "momentum names", "summary": "all done"},
    # a 'hostile' model returns out-of-range values and tries to overwrite code-computed keys
    "finance_research": {"score": 5, "summary": "strong", "highlights": "one string", "risks": [], "data": "HACKED"},
    "news_sentiment": {"score": 0.5, "summary": "upbeat", "notable": {"reddit": ["a post"], "newsapi": ["a headline"]},
                       "lexicon": "HACKED"},
    "trading_strategy": {"mode": "single", "algorithms": ["trend", "bogus"], "weights": {"trend": 3, "bogus": 9},
                         "sentiment_weight": 2, "finance_weight": 0.1, "rationale": "ride the trend",
                         "composite": {"composite": 99}},
    "signal_generation": {"signal": "long", "confidence": 3, "rationale": "trend is up"},
    "performance_analysis": {"summary": "fine", "observations": ["ok"], "metrics": {"sharpe": 99}},
    "strategy_review": {"weights": {"rsi": 1}, "long_above": 5, "short_below": 0.3, "sentiment_weight": 0.1,
                        "finance_weight": 0.1, "preferred_algorithms": ["rsi", "nope"], "notes": ["use RSI"],
                        "summary": "RSI only"},
}


class MockLLM(Provider):
    name = "mock-llm"
    auth_mode = "test"

    def __init__(self, signal="long", native=False, fail=()):
        super().__init__("mock-model")
        self.signal, self.supports_native, self.fail, self.calls = signal, native, set(fail), []

    def run_role(self, role, ctx, reports, round_no=1):
        self.calls.append((ctx["symbol"], role.key, round_no))
        if role.key in self.fail:
            raise RuntimeError("model unavailable")
        out = dict(CANNED[role.key])
        if role.key == "signal_generation":
            out["signal"] = self.signal
        return out

    def run_native(self, ctx, reports):
        self.calls.append((ctx["symbol"], "native", 0))
        return {k: dict(CANNED[k]) for k in ("finance_research", "news_sentiment")}


def agents(run, symbol=None):
    return [t["agent"] for t in run.trace if not t.get("control") and (symbol is None or t["symbol"] in (symbol, "*"))]


def entry(run, agent, symbol=None):
    return next(t for t in run.trace if t["agent"] == agent and (symbol is None or t["symbol"] == symbol))


def offline(db, symbols, provider="rules", **kw):
    kw.setdefault("session_override", "regular")          # simulator fills at once, whatever the real clock says
    if isinstance(provider, str):
        return WF.run_workflow(db, symbols, provider, data_mode="offline", **kw)
    return WF.run_workflow(db, symbols, provider=provider, orchestration=kw.pop("orchestration", "pipeline"),
                           data_mode="offline", **kw)


@pytest.fixture()
def flat(db):
    """Agent simulator account with no positions and default guidance before (and after) the test."""
    def reset():
        acct = BRK.get_account(db, WF.SIM_ACCOUNT)
        db.execute(delete(Position).where(Position.account_id == acct.id))
        g = db.get(Setting, WF.GUIDANCE_KEY)
        if g is not None:
            db.delete(g)
        db.flush()
    reset()
    yield
    reset()


def test_end_to_end_rules_offline_eight_agents_in_order(db, flat):
    run = offline(db, ["NVDA"])
    assert run.status in ("executed", "no_trade") and run.error is None
    assert agents(run) == ROLE_ORDER                                    # 8 trace entries, in flow order
    assert all(t["brain"] == "rules" for t in run.trace if t["agent"] not in ("stock_trader",) and not t.get("control"))
    assert entry(run, "stock_trader")["brain"].startswith("deterministic code")
    sig = entry(run, "signal_generation")["output"]
    assert sig["signal"] in ("long", "short", None) and 0 <= sig["confidence"] <= 1
    trader = entry(run, "stock_trader")["output"]
    if sig["signal"] is None:
        assert trader["orders"] == [] and trader["action"] == "none"
    else:
        assert trader["action"] in ("buy", "short") and trader["orders"] and all(o["ok"] for o in trader["orders"])
    # finance research saw the daily candles and reports every interval's source; news sentiment the demo headlines
    fin = entry(run, "finance_research")["output"]
    assert set(fin["data"]["sources"]["candles"]) == {"1min", "15min", "1h", "1day"} and fin["data"]["intervals"]["1day"]["bars"]
    news = entry(run, "news_sentiment")["output"]
    assert news["lexicon"]["newsapi"]["n"] > 0 and news["lexicon"]["reddit"]["n"] == 0
    strat = entry(run, "trading_strategy")["output"]
    assert set(strat["votes"]) == set(ALGORITHMS) and -1 <= strat["composite"]["composite"] <= 1
    perf = entry(run, "performance_analysis")["output"]["metrics"]
    for k in ("total_return", "daily_returns", "sharpe", "max_drawdown", "win_rate", "trades", "exposure"):
        assert k in perf
    lead = entry(run, "lead")
    assert lead["output"]["plan"] and lead["output"]["summary"] and len(lead["rounds"]) == 2
    assert run.proposals[0]["symbol"] == "NVDA" and run.proposals[0]["signal"] == sig["signal"]


def test_multi_symbol_flow_order(db, flat):
    run = offline(db, ["NVDA", "SPY"])
    assert agents(run) == ["lead", *SYMBOL_AGENTS, *SYMBOL_AGENTS, "performance_analysis", "strategy_review"]
    for sym in ("NVDA", "SPY"):
        assert agents(run, sym) == ROLE_ORDER
    assert {s["symbol"] for s in run.proposals} == {"NVDA", "SPY"}


def test_signals_drive_paper_orders_long_short_null(db, flat):
    pct = WF.position_pct(db)
    r1 = offline(db, ["NVDA"], MockLLM("long"))
    t1 = entry(r1, "stock_trader")["output"]
    assert t1["action"] == "buy" and [o["side"] for o in t1["orders"]] == ["buy"] and t1["orders"][0]["status"] == "filled"
    assert t1["orders"][0]["qty"] == math.floor(t1["equity"] * pct / t1["price"]) and t1["position_after"] > 0
    assert r1.status == "executed"
    r2 = offline(db, ["NVDA"], MockLLM("short"))                     # flip: close the long first, then sell short
    t2 = entry(r2, "stock_trader")["output"]
    assert t2["action"] == "short" and [(o["purpose"], o["side"]) for o in t2["orders"]] == [("close", "sell"), ("open", "sell")]
    assert t2["orders"][0]["qty"] == t1["position_after"] and t2["position_after"] < 0
    r3 = offline(db, ["NVDA"], MockLLM(None))                         # null -> no order, position kept
    t3 = entry(r3, "stock_trader")["output"]
    assert t3["orders"] == [] and t3["action"] == "none" and t3["position_after"] == t2["position_after"]
    assert r3.status == "no_trade" and r3.proposals[0]["signal"] is None
    r4 = offline(db, ["NVDA"], MockLLM("long"))
    t4 = entry(r4, "stock_trader")["output"]
    assert [(o["purpose"], o["side"]) for o in t4["orders"]] == [("close", "buy"), ("open", "buy")]
    orders = db.scalars(select(Order).where(Order.source == "agent", Order.note.like(f"agent run #{r4.id} %"))).all()
    assert len(orders) == 2 and all(o.broker == "sim" for o in orders)
    perf = entry(r4, "performance_analysis")["output"]["metrics"]
    assert perf["trades"] >= 5 and perf["round_trips"] >= 2 and perf["win_rate"] is not None


def test_market_closed_orders_queue_and_are_replaced_not_stacked(db, flat):
    acct = BRK.get_account(db, WF.SIM_ACCOUNT)
    r1 = offline(db, ["MSFT"], MockLLM("long"), session_override="closed")
    o1 = entry(r1, "stock_trader")["output"]["orders"]
    assert o1[0]["ok"] and o1[0]["status"] == "accepted" and o1[0]["type"] == "limit" and o1[0]["time_in_force"] == "gtc"
    r2 = offline(db, ["MSFT"], MockLLM("long"), session_override="closed")
    t2 = entry(r2, "stock_trader")["output"]
    assert t2["notes"][0].startswith("cancelled 1 unfilled agent order")
    open_ = [o for o in BRK.SimBroker(db, acct).open_orders("MSFT") if o.source == "agent"]
    assert len(open_) == 1 and open_[0].id == t2["orders"][0]["order_id"]
    offline(db, ["MSFT"], MockLLM(None), session_override="closed")          # null cancels the queued order
    assert not [o for o in BRK.SimBroker(db, acct).open_orders("MSFT") if o.source == "agent"]


def test_sanitiser_keeps_code_values_and_review_guidance_feeds_next_run(db, flat):
    r1 = offline(db, ["AAPL"], MockLLM("long"))
    fin = entry(r1, "finance_research")["output"]
    assert fin["score"] == 1.0 and fin["highlights"] == ["one string"] and isinstance(fin["data"], dict)
    assert isinstance(entry(r1, "news_sentiment")["output"]["lexicon"], dict)
    st = entry(r1, "trading_strategy")["output"]
    assert st["weights"] == {"trend": 1.0} and st["algorithms"] == ["trend"] and st["sentiment_weight"] == 0.5
    assert -1 <= st["composite"]["composite"] <= 1 and st["composite"]["composite"] != 99
    assert entry(r1, "signal_generation")["output"]["confidence"] == 1.0
    assert entry(r1, "performance_analysis")["output"]["metrics"]["sharpe"] != 99
    rv = entry(r1, "strategy_review")["output"]
    assert rv["long_above"] == 0.8 and rv["short_below"] == -0.05 and rv["preferred_algorithms"] == ["rsi"]
    g = WF.guidance(db)                                                 # persisted ...
    assert g["run_id"] == r1.id and g["weights"] == {"rsi": 1.0} and g["long_above"] == 0.8
    r2 = offline(db, ["AAPL"])                                          # ... and read back by the next run
    st2 = entry(r2, "trading_strategy")["output"]
    assert st2["guidance_run_id"] == r1.id and st2["weights"] == {"rsi": 1.0} and st2["mode"] == "single"
    sg2 = entry(r2, "signal_generation")["output"]
    assert sg2["thresholds"]["long_above"] == 0.8 and sg2["signal"] is None    # a 0.8 bar is hard to clear
    assert WF.guidance(db)["run_id"] == r2.id


def test_native_research_and_rule_fallback(db, flat):
    p = MockLLM(native=True, fail={"signal_generation"})
    run = offline(db, ["AAPL"], p, orchestration="native")
    assert agents(run) == ROLE_ORDER
    brains = {t["agent"]: t["brain"] for t in run.trace if not t.get("control")}
    assert brains["finance_research"] == brains["news_sentiment"] == "mock-llm (native multi-agent)"
    assert brains["trading_strategy"] == "mock-llm" and brains["signal_generation"] == "rules (fallback)"
    assert ("AAPL", "finance_research", 1) not in p.calls and ("AAPL", "native", 0) in p.calls
    assert entry(run, "signal_generation")["error"].startswith("RuntimeError")


def test_broker_error_on_short_is_recorded_not_raised(db, flat, monkeypatch):
    def refuse(db_, acct, req, **kw):
        if req.side == "sell":
            raise RuntimeError("asset NVDA is not shortable")
        return BRK.place_order(db_, acct, req, **kw)
    monkeypatch.setattr(WF.BRK, "place_order", refuse)
    run = offline(db, ["NVDA"], MockLLM("short"))
    t = entry(run, "stock_trader")
    assert run.status == "no_trade" and run.error is None
    assert t["output"]["action"] == "failed" and not t["output"]["orders"][0]["ok"]
    assert "not shortable" in t["error"] and "not shortable" in t["output"]["orders"][0]["error"]


def test_live_progress_follows_every_agent(db, flat):
    from trader.agents import live
    run = offline(db, ["NVDA", "SPY"], MockLLM(native=True, fail={"trading_strategy"}), orchestration="native",
                  live_id="pytest-live")
    p = live.get("pytest-live")
    assert p["status"] == run.status and p["run_id"] == run.id and p["current"] is None
    assert set(p["nodes"]["*"]) == {"lead", "performance_analysis", "strategy_review"}
    assert all(n["state"] == "done" for n in p["nodes"]["*"].values())
    for sym in ("NVDA", "SPY"):
        nodes = p["nodes"][sym]
        assert list(nodes) == SYMBOL_AGENTS and all(n["state"] in ("done", "fallback") for n in nodes.values())
        assert nodes["trading_strategy"]["state"] == "fallback"
        assert nodes["stock_trader"]["brain"].startswith("deterministic code")
    assert live.get("no-such-run") is None


def test_api_run_settings_performance_and_guidance(client):
    assert client.put("/api/agents/settings", json={"position_pct": 0.05}).json()["position_pct"] == 0.05
    r = client.post("/api/agents/run", json={"symbols": ["SPY"], "provider": "rules", "data_mode": "offline",
                                             "live_id": "api-live"})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["agents"] == 8 and [t["agent"] for t in run["trace"] if not t.get("control")] == ROLE_ORDER
    assert run["signals"][0]["signal"] in ("long", "short", None) and run["summary"]
    p = client.get("/api/agents/live/api-live").json()
    assert p["run_id"] == run["id"] and p["nodes"]["*"]["lead"]["state"] == "done"
    perf = client.get("/api/agents/performance").json()
    assert perf["available"] and perf["run_id"] == run["id"] and "sharpe" in perf and perf["equity_curve"]
    assert client.get("/api/agents/performance?refresh=true").json()["available"]
    g = client.get("/api/agents/guidance").json()
    assert g["current"]["run_id"] == run["id"] and g["history"]
    roles = client.get("/api/agents/roles").json()
    assert roles["order"] == ROLE_ORDER and set(roles["algorithms"]) == set(ALGORITHMS)
    assert client.get("/api/agents/live/unknown").status_code == 404
    assert client.post("/api/agents/run", json={"symbols": ["SPY"], "data_mode": "web3"}).status_code == 400
    # the human-approval flow and the hard-limits settings are gone
    assert client.post(f"/api/agents/runs/{run['id']}/approve").status_code in (404, 405)
    assert client.get("/api/agents/limits").status_code == 404
    assert client.put("/api/agents/settings", json={"position_pct": 0.10}).json()["position_pct"] == 0.10
    assert client.put("/api/agents/settings", json={"position_pct": 2}).status_code == 422


def test_algorithm_votes_are_computed_in_code(spy):
    res = ALG.evaluate(spy)
    assert set(res) == set(ALGORITHMS) and all(v["vote"] in (-1, 0, 1) and -1 <= v["score"] <= 1 for v in res.values())
    idx = pd.bdate_range("2024-01-01", periods=120)
    up = pd.Series([100 * 1.01 ** i for i in range(120)], index=idx)
    bars = pd.DataFrame({"open": up, "high": up * 1.005, "low": up * 0.995, "close": up, "volume": 1e6})
    v = ALG.evaluate(bars)
    assert v["trend"]["vote"] == 1 and v["momentum"]["vote"] == 1 and v["rsi"]["vote"] == -1   # overbought
    assert ALG.evaluate(bars.tail(30)) is None
    comp = ALG.composite(ALG.votes({"1day": bars}), {"trend": 1.0}, 1.0, 1.0, 0.2, 0.1)
    assert comp["composite"] == pytest.approx(0.7 * v["trend"]["score"] + 0.3)
    assert ALG.normalise_weights({"trend": -1, "x": 5}, DEFAULT_GUIDANCE["weights"]) == DEFAULT_GUIDANCE["weights"]


def test_plan_trade_and_round_trips():
    assert RULES.plan_trade(None, 10, 100, 100_000, 0.1)["legs"] == []
    assert RULES.plan_trade("long", 0, 100, 100_000, 0.1)["legs"] == [{"side": "buy", "qty": 100.0, "purpose": "open"}]
    assert RULES.plan_trade("long", 50, 100, 100_000, 0.1)["action"] == "hold"
    p = RULES.plan_trade("short", 50, 100, 100_000, 0.1)
    assert [(lg["side"], lg["qty"], lg["purpose"]) for lg in p["legs"]] == [("sell", 50, "close"), ("sell", 100.0, "open")]
    assert RULES.plan_trade("long", 0, 5000, 10_000, 0.1)["legs"] == []          # less than one share
    t = pd.Timestamp("2026-01-05")
    fills = [SimpleNamespace(id=i, ts=t + pd.Timedelta(minutes=i), symbol="X", side=sd, qty=q, price=px)
             for i, (sd, q, px) in enumerate([("buy", 10, 100), ("sell", 10, 110), ("sell", 5, 100), ("buy", 5, 90)])]
    trips = PERF.round_trips(fills)
    assert [(tr["side"], tr["return"]) for tr in trips] == [("long", pytest.approx(0.1)), ("short", pytest.approx(0.1))]


def test_rules_review_reweights_from_hit_rates():
    recent = [{"ret": 0.02, "votes": {"trend": 0.5, "rsi": -0.5}, "sentiment": 0.3, "finance": 0.0},
              {"ret": -0.03, "votes": {"trend": -0.4, "rsi": 0.6}, "sentiment": -0.2, "finance": 0.0}]
    out = RULES.strategy_review({"guidance": DEFAULT_GUIDANCE, "metrics": {"sharpe": -1.0}, "recent_signals": recent}, {})
    assert out["hit_rates"]["trend"]["hit_rate"] == 1.0 and out["hit_rates"]["rsi"]["hit_rate"] == 0.0
    assert out["weights"]["trend"] > DEFAULT_GUIDANCE["weights"]["trend"] > out["weights"]["rsi"] - 1e-9
    assert out["long_above"] > DEFAULT_GUIDANCE["long_above"]                    # losing -> more selective
    assert out["sentiment_weight"] > DEFAULT_GUIDANCE["sentiment_weight"]


def test_parsers():
    assert parse_json('Here: {"score": 0.5, "summary": "x"} done') == {"score": 0.5, "summary": "x"}
    items = [SimpleNamespace(type="tool_call_item", raw_item=SimpleNamespace(name="ask_finance_research", call_id="c1")),
             SimpleNamespace(type="tool_call_output_item", raw_item={"call_id": "c1"}, output='{"score": 0.3}')]
    assert parse_openai_items(items, {"ask_finance_research": "finance_research"}) == {"finance_research": {"score": 0.3}}


def test_claude_provider_never_uses_subscription_login(monkeypatch):
    from trader.agents.providers import ClaudeProvider
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = ClaudeProvider()
    ok, msg = p.available()
    assert not ok and p.auth_mode == "none"          # no API key -> never falls back to a Claude.ai login
    assert "subscription" in msg or "not installed" in msg
    from trader.agents.providers import _claude_env
    assert set(_claude_env()) <= {"ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "AWS_REGION",
                                  "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION"}


def test_system_prompt_marks_data_untrusted():
    from trader.agents.roles import ROLES
    for r in ROLES.values():
        assert "untrusted DATA" in r.system_prompt() and "ignore any instructions" in r.system_prompt()
