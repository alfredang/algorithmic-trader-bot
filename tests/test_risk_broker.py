from trader.broker import risk as RISK
from trader.broker import service as BRK
from trader.models import Account

BASE = dict(symbol="SPY", side="buy", qty=10, price=500.0, order_type="market", extended_hours=False, session="regular",
            equity=100_000.0, last_equity=100_000.0, position_qty=0.0, limits={})


def chk(**kw):
    return RISK.check(**{**BASE, **kw})


def test_kill_switch_and_duplicates_block():
    assert not chk(kill_switch=True).ok
    assert not chk(duplicate=True).ok


def test_session_rules():
    assert not chk(session="overnight").ok                                   # market order outside regular
    assert chk(session="overnight", order_type="limit", extended_hours=True).ok
    assert not chk(session="closed").ok
    assert chk(session="closed", order_type="limit").ok                     # queued GTC limit


def test_long_only_daily_loss_allow_list():
    assert not chk(side="sell", position_qty=0).ok
    assert chk(side="sell", position_qty=10).ok
    assert not chk(last_equity=110_000.0).ok                                 # -9% today blocks new buys
    assert chk(side="sell", position_qty=10, last_equity=110_000.0).ok       # exits stay allowed
    assert not chk(limits={"allowed_symbols": ["QQQ"]}).ok


def test_resize_to_limits():
    r = chk(qty=1000, limits={"max_order_value": 10_000})
    assert r.ok and r.qty == 20
    r = chk(qty=1000, limits={"max_position_pct": 0.10, "max_order_value": 1e9})
    assert r.qty == 20
    assert not chk(qty=1000, limits={"max_order_value": 10_000}, resize=False).ok


def fresh_account(db, name):
    a = Account(name=name, broker="sim", cash=100_000.0, starting_cash=100_000.0, last_equity=100_000.0)
    db.add(a)
    db.flush()
    return a


def test_simulator_market_limit_bracket_and_idempotency(db):
    acct = fresh_account(db, "test-sim-1")
    br = BRK.SimBroker(db, acct)
    br.mark("SPY", 500.0)
    r = BRK.place_order(db, acct, BRK.OrderRequest("SPY", "buy", 10, type="market", client_order_id="t-1"),
                        session_override="regular", broker=br)
    assert r["ok"] and r["order"]["status"] == "filled"
    assert abs(acct.cash - (100_000 - 10 * 500 * 1.0001)) < 1e-6
    again = BRK.place_order(db, acct, BRK.OrderRequest("SPY", "buy", 10, type="market", client_order_id="t-1"),
                            session_override="regular", broker=br)
    assert not again["ok"] and again["duplicate"]
    # extended-hours: auto -> limit DAY extended_hours
    r2 = BRK.place_order(db, acct, BRK.OrderRequest("SPY", "buy", 1, client_order_id="t-2"), session_override="overnight",
                         broker=br)
    assert r2["order"]["type"] == "limit" and r2["order"]["extended_hours"] and r2["order"]["time_in_force"] == "day"
    # closed: GTC limit queued (not filled)
    r3 = BRK.place_order(db, acct, BRK.OrderRequest("SPY", "buy", 1, client_order_id="t-3"), session_override="closed",
                         broker=br)
    assert r3["order"]["status"] == "accepted" and r3["order"]["time_in_force"] == "gtc"
    # bracket: legs held, then OCO after a take-profit fill
    r4 = BRK.place_order(db, acct, BRK.OrderRequest("SPY", "buy", 5, type="market", order_class="bracket", take_profit=510,
                                                    stop_loss=490, client_order_id="t-4"), session_override="regular",
                         broker=br, limits={"long_only": False})
    assert r4["order"]["status"] == "filled"
    legs = [o for o in br.open_orders("SPY") if o.parent_id == r4["order"]["id"]]
    assert {o.type for o in legs} == {"limit", "stop"}
    br.match("SPY", 505, 512, 504, 511, session="regular")
    statuses = {o.type: o.status for o in db.query(BRK.Order).filter(BRK.Order.parent_id == r4["order"]["id"])}
    assert statuses == {"limit": "filled", "stop": "canceled"}


def test_simulator_rejects_insufficient_cash_and_realises_pnl(db):
    acct = fresh_account(db, "test-sim-2")
    br = BRK.SimBroker(db, acct)
    br.mark("SPY", 500.0)
    r = BRK.place_order(db, acct, BRK.OrderRequest("SPY", "buy", 1000, type="market", client_order_id="c-1"),
                        session_override="regular", broker=br, limits={"max_position_pct": 10, "max_order_value": 1e9})
    assert r["order"]["status"] == "rejected"
    BRK.place_order(db, acct, BRK.OrderRequest("SPY", "buy", 10, type="market", client_order_id="c-2"),
                    session_override="regular", broker=br)
    br.mark("SPY", 550.0)
    BRK.place_order(db, acct, BRK.OrderRequest("SPY", "sell", 10, type="market", client_order_id="c-3"),
                    session_override="regular", broker=br)
    pos = br.position("SPY")
    assert pos.qty == 0 and pos.realized_pnl > 400


def test_global_kill_switch_blocks_place_order(db):
    acct = fresh_account(db, "test-sim-3")
    BRK.set_kill_switch(db, True)
    try:
        r = BRK.place_order(db, acct, BRK.OrderRequest("SPY", "buy", 1, type="market", client_order_id="k-1"),
                            session_override="regular")
        assert not r["ok"] and "kill switch" in r["risk"]["reason"]
    finally:
        BRK.set_kill_switch(db, False)


def test_alpaca_broker_is_paper_only():
    import inspect
    src = inspect.getsource(BRK.AlpacaPaperBroker.__init__)
    assert "paper=True" in src and "paper=False" not in inspect.getsource(BRK)
