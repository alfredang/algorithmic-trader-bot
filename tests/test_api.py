"""API smoke tests (TestClient, offline)."""


def test_health_and_pages(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert "Quant Trading Simulator" in client.get("/").text
    for page in ("pipeline", "dashboard", "labs", "data", "strategies", "builder", "backtest", "research", "trading",
                 "analytics", "agents", "integrations", "settings", "help"):
        assert client.get(f"/static/pages/{page}.html").status_code == 200, page
    assert client.get("/api/openapi.json").json()["info"]["title"]


def test_read_endpoints(client):
    for path in ("/api/system/status", "/api/instruments", "/api/strategies", "/api/strategies/taxonomy", "/api/backtests",
                 "/api/research", "/api/bots", "/api/orders", "/api/positions", "/api/accounts", "/api/agents/providers",
                 "/api/agents/roles", "/api/integrations", "/api/glossary", "/api/clock", "/api/settings",
                 "/api/analytics/summary", "/api/costs/presets", "/api/metrics/definitions", "/api/webhooks/template",
                 "/api/data/sources", "/api/news?symbol=NVDA", "/api/agents/always-on", "/api/agents/memory"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text[:200])


def test_bars_with_indicators(client):
    d = client.get("/api/data/bars?symbol=SPY&start=2025-01-01&indicators=sma:200,rsi,macd").json()
    assert d["count"] > 200 and d["indicators"]["sma:200"]["series"]["sma"][0][1] is not None   # warm-up from history
    assert client.get("/api/data/quality?symbol=SPY").json()["status"] in ("OK", "CHECK")


def test_backtest_roundtrip_and_exports(client):
    r = client.post("/api/backtests", json={"strategy_key": "ema_cross", "symbols": ["SPY"], "params": {"fast": 20, "slow": 50},
                                            "config": {"costs": "alpaca_retail", "stop_loss_pct": 0.1}})
    assert r.status_code == 200, r.text
    bt = r.json()
    assert bt["metrics"]["trades"] > 0 and bt["cost_summary"]["total"] > 0 and bt["series"]["equity"]
    assert client.get(f"/api/backtests/{bt['id']}/tearsheet.pdf").content[:4] == b"%PDF"
    assert client.get(f"/api/backtests/{bt['id']}/export.csv").text.startswith("date,")
    assert client.post("/api/backtests", json={"strategy_key": "nope"}).status_code == 400
    assert len(client.get(f"/api/backtests/compare?ids={bt['id']},1").json()) == 2


def test_research_endpoints(client):
    assert client.post("/api/research/hypothesis", json={"symbol": "SPY"}).json()["status"] == "done"
    ab = client.post("/api/research/abtest", json={"a": {"strategy_key": "trend_filter"}, "b": {"strategy_key": "dip_buy"}}).json()
    assert "decision" in ab["result"]
    dg = client.post("/api/research/diagnostics", json={"strategy_key": "ema_cross"}).json()
    assert len(dg["result"]["checks"]) == 5


def test_custom_strategy_crud(client):
    code = client.get("/api/strategies/templates").json()[0]["code"]
    s = client.post("/api/strategies", json={"code": code, "symbol": "SPY"}).json()
    assert s["custom"] and s["key"].startswith("custom_")
    bt = client.post("/api/backtests", json={"strategy_key": s["key"], "symbols": ["SPY"]})
    assert bt.status_code == 200
    assert client.delete(f"/api/strategies/{s['key']}").status_code == 200
    assert client.post("/api/strategies", json={"code": "import os"}).status_code == 422


def test_bot_lifecycle(client):
    b = client.post("/api/bots", json={"name": "pytest bot", "strategy_key": "ema_cross", "symbols": ["SPY"],
                                       "schedule": "every 10s", "replay_start": "2025-06-02"}).json()
    for _ in range(5):
        r = client.post(f"/api/bots/{b['id']}/run-now").json()
        assert r["result"]["status"] == "ok", r
    assert len(client.get(f"/api/bots/{b['id']}/equity").json()) == 5
    assert client.post(f"/api/bots/{b['id']}/kill").json()["kill_switch"]
    assert client.post(f"/api/bots/{b['id']}/run-now").json()["result"]["status"] == "halted"
    assert client.post(f"/api/bots/{b['id']}/release").json()["kill_switch"] is False
    assert client.post("/api/bots", json={"name": "x", "strategy_key": "ema_cross", "schedule": "nonsense"}).status_code == 400


def test_manual_order_ticket(client):
    r = client.post("/api/orders", json={"symbol": "SPY", "side": "buy", "qty": 2, "type": "market", "session_override": "regular"}).json()
    assert r["ok"] and r["order"]["status"] == "filled"
    blocked = client.post("/api/orders", json={"symbol": "SPY", "side": "buy", "qty": 2, "type": "market",
                                               "session_override": "overnight"}).json()
    assert not blocked["ok"]


def test_tradingview_webhook_selftest_and_secret(client):
    r = client.post("/api/integrations/tradingview/test").json()
    assert r["ok"], r
    assert client.post("/api/webhooks/tradingview", content=b"not json").status_code == 400
    assert client.post("/api/webhooks/tradingview", json={"secret": "wrong", "ticker": "SPY", "action": "buy", "qty": 1}).status_code == 401
    alerts = client.get("/api/webhooks/alerts").json()
    assert alerts and all(a["payload"] is None or a["payload"].get("secret") in (None, "***") for a in alerts)


def test_pipeline_status_endpoint(client):
    st = client.get("/api/pipeline/status").json()
    main = [s for s in st["stages"] if not s["side_input"]]
    assert [s["key"] for s in main] == ["ingestion", "quality", "news", "features", "strategy", "search", "backtest",
                                        "abtest", "agents", "risk", "forward", "execution", "analytics", "reporting"]
    assert {s["key"] for s in st["stages"] if s["side_input"]} == {"webhook", "scheduler"}
    by = {s["key"]: s for s in st["stages"]}
    assert by["ingestion"]["status"] == "ok" and by["ingestion"]["metrics"]["bars_cached"] > 0
    assert by["backtest"]["metrics"]["last_id"] and "sharpe" in by["analytics"]["metrics"]
    assert by["agents"]["disabled"] and by["agents"]["hint"]                  # AI_PROVIDER=rules in tests
    assert len(st["edges"]) == 13
    assert client.get("/api/pipeline/events?stage=backtest").json()
    lc = client.get("/api/pipeline/lifecycle?strategy_key=ema_cross").json()
    assert [s["key"] for s in lc["steps"]] == ["idea", "backtest", "abtest", "diagnostics", "forward", "live_paper", "analytics"]


def test_course_labs(client):
    labs = client.get("/api/labs").json()
    assert len(labs["labs"]) == 20 and {lab["topic"] for lab in labs["labs"]} == {1, 2, 3, 4}
    lab = client.post("/api/labs/8/steps/0", json={"done": True}).json()
    assert lab["steps"][0]["done"] and lab["steps"][0]["completed_at"]
    assert not client.post("/api/labs/8/reset").json()["steps"][0]["done"]
    for lab in labs["labs"]:
        detail = client.get(f"/api/labs/{lab['id']}").json()
        assert detail["steps"] and all(s["title"] and s["instruction"] for s in detail["steps"])


def test_events_and_kill_switch(client):
    last = client.get("/api/events").json()["last_id"]
    client.post("/api/kill-switch", json={"on": True})
    assert client.get("/api/kill-switch").json()["on"]
    client.post("/api/kill-switch", json={"on": False})
    ev = client.get(f"/api/events?after={last}").json()["events"]
    assert any(e["kind"] == "kill_switch" for e in ev)


def test_secrets_never_returned(client):
    import json
    body = json.dumps(client.get("/api/integrations").json())
    assert "secret_key" not in body.lower() or "APCA_API_SECRET_KEY" in body
