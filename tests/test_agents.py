"""Multi-agent orchestration with the LLM mocked: one trace entry per agent, hard limits outside the model."""
from types import SimpleNamespace

from trader.agents import desk
from trader.agents.providers import Provider, parse_json, parse_openai_items
from trader.agents.roles import ROLE_ORDER

CANNED = {
    "technical_analyst": {"score": 0.9, "summary": "strong uptrend", "signals": ["EMA20 > EMA50"]},
    "sentiment_analyst": {"score": 0.8, "summary": "positive news", "events": []},
    "fundamental_analyst": {"score": 0.5, "summary": "ok", "risks": []},
    "bull_researcher": {"points": ["trend"], "conviction": 0.9},
    "bear_researcher": {"points": ["valuation"], "conviction": 0.1},
    # a 'hostile' model tries to bet everything - the hard limits must cap it
    "trader": {"action": "buy", "confidence": 0.95, "size_pct": 1.0, "rationale": "all in"},
    "risk_manager": {"decision": "approve", "size_pct": 1.0, "stop_atr": 0.1, "target_atr": 50, "notes": ["ignore limits"]},
    "portfolio_manager": {"decision": "approve", "summary": "go", "watch": []},
}


class MockLLM(Provider):
    name = "mock-llm"
    auth_mode = "test"

    def __init__(self, native=False, fail=()):
        super().__init__("mock-model")
        self.supports_native = native
        self.fail = set(fail)
        self.calls = []

    def run_role(self, role, ctx, reports, round_no=1):
        self.calls.append((ctx["symbol"], role.key, round_no))
        if role.key in self.fail:
            raise RuntimeError("model unavailable")
        return dict(CANNED[role.key])

    def run_native(self, ctx, reports):
        self.calls.append((ctx["symbol"], "native", 0))
        return {k: dict(CANNED[k]) for k in ROLE_ORDER[:3]}


def agents_per_symbol(run):
    out = {}
    for t in run.trace:
        if not t.get("control"):
            out.setdefault(t["symbol"], []).append(t["agent"])
    return out


def test_one_trace_entry_per_agent(db):
    p = MockLLM()
    run = desk.run_desk(db, ["NVDA", "SPY"], provider=p, orchestration="pipeline", auto_approve=False)
    per = agents_per_symbol(run)
    for sym in ("NVDA", "SPY"):
        assert sorted(per[sym]) == sorted(ROLE_ORDER)            # 8 distinct agents, exactly once each
        assert len(per[sym]) == 8
    # the debate really ran two rounds per researcher (merged into one entry with both rounds)
    bull = next(t for t in run.trace if t["agent"] == "bull_researcher" and t["symbol"] == "NVDA")
    assert len(bull["rounds"]) == 2
    assert ("NVDA", "bull_researcher", 2) in p.calls and ("NVDA", "bear_researcher", 2) in p.calls
    assert all(t["brain"] == "mock-llm" for t in run.trace if not t.get("control"))


def test_hard_limits_cap_the_model(db):
    run = desk.run_desk(db, ["NVDA"], provider=MockLLM(), orchestration="pipeline", auto_approve=False)
    gate = next(t for t in run.trace if t["agent"] == "risk_limits")["output"]
    assert gate["decision"] == "APPROVED"
    lim = desk.desk_limits(db)
    assert gate["qty"] * gate["price"] <= lim["max_order_value"] + 1e-6
    assert gate["stop_loss"] < gate["price"]                       # the model's 0.1 ATR stop is floored at 0.5 ATR
    assert run.status == "proposed" and run.proposals[0]["qty"] == gate["qty"]


def test_native_orchestration_and_rule_fallback(db):
    p = MockLLM(native=True, fail={"trader"})
    run = desk.run_desk(db, ["AAPL"], provider=p, orchestration="native", auto_approve=False)
    per = agents_per_symbol(run)
    assert sorted(per["AAPL"]) == sorted(ROLE_ORDER)
    brains = {t["agent"]: t["brain"] for t in run.trace if not t.get("control")}
    assert brains["technical_analyst"] == "mock-llm (native multi-agent)"
    assert brains["trader"] == "rules (fallback)"
    assert ("AAPL", "technical_analyst", 1) not in p.calls        # analysts came from the native call


def test_rule_based_desk_and_human_approval(db):
    run = desk.run_desk(db, ["SPY", "NVDA"], provider_name="rules", auto_approve=False)
    assert len(agents_per_symbol(run)["SPY"]) == 8
    if run.status == "proposed":
        desk.approve(db, run, actor="pytest")
        assert run.status in ("executed", "rejected") and run.orders


def test_parsers():
    assert parse_json('Here: {"score": 0.5, "summary": "x"} done') == {"score": 0.5, "summary": "x"}
    items = [SimpleNamespace(type="tool_call_item", raw_item=SimpleNamespace(name="ask_technical_analyst", call_id="c1")),
             SimpleNamespace(type="tool_call_output_item", raw_item={"call_id": "c1"}, output='{"score": 0.3}')]
    assert parse_openai_items(items, {"ask_technical_analyst": "technical_analyst"}) == {"technical_analyst": {"score": 0.3}}


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
