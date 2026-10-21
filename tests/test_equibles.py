"""Equibles provider (offline: the HTTP layer is replaced) and its key / company-data endpoints."""
import pytest

from trader.config import get_settings
from trader.data import providers as P

KEY = "eq_testkey_1234567890abcdef"
ROWS = [  # newest first, as the API returns them
    {"date": "2026-07-10", "open": 202.0, "high": 211.0, "low": 201.0, "close": 210.0, "adjustedClose": 210.0, "volume": 100},
    {"date": "2026-07-09", "open": 204.0, "high": 205.0, "low": 198.0, "close": 200.0, "adjustedClose": 199.0, "volume": 200},
]


def _set_key(client, value=KEY):
    if value:
        assert client.put("/api/integrations/equibles/keys", json={"values": {"EQUIBLES_API_KEY": value}}).status_code == 200
    else:
        client.put("/api/integrations/equibles/keys", json={"clear": ["EQUIBLES_API_KEY"]})


@pytest.fixture()
def eq():
    return P.EquiblesProvider()


def test_parse_sorts_ascending_and_applies_dividend_adjustment(eq):
    df = eq.parse(ROWS, "NVDA")
    assert list(df.columns) == P.COLUMNS and df.index.is_monotonic_increasing
    first = df.iloc[0]                                    # 2026-07-09: factor 199/200
    assert first["close"] == pytest.approx(199.0) and first["open"] == pytest.approx(204.0 * 0.995)
    assert df.iloc[1]["close"] == pytest.approx(210.0)    # factor 1 on the newest bar
    with pytest.raises(P.DataError):
        eq.parse([], "NVDA")


def test_bars_pages_until_has_more_is_false(eq, monkeypatch):
    calls = []

    def fake(path, params=None):
        calls.append(params["offset"])
        return {"data": ROWS[:1] if params["offset"] == 0 else ROWS[1:], "meta": {"hasMore": params["offset"] == 0}}
    monkeypatch.setattr(eq, "_get", fake)
    df = eq.bars("NVDA", "1Day", start="2026-07-01")
    assert calls == [0, eq.PAGE] and len(df) == 2
    with pytest.raises(P.DataError, match="end-of-day"):
        eq.bars("NVDA", "1Hour")


def test_company_reports_missing_sections_caches_and_stops_on_auth_error(eq, monkeypatch):
    n = {"calls": 0}

    def fake(path, params=None):
        n["calls"] += 1
        if path.endswith("valuation-multiples"):
            raise P.EquiblesError("Equibles 404: Stock not found.", 404)
        if path == "/prices/latest":
            return {"data": [{"ticker": "SPY", "close": 600.0}], "notFound": []}
        if path.endswith("ownership-summary"):
            return {"ticker": "SPY", "institutional": {"percentOutstanding": 50.0}}
        return {"data": [{"x": 1}], "meta": {"hasMore": False}}
    monkeypatch.setattr(eq, "_get", fake)
    snap = eq.company("spy")
    assert snap["symbol"] == "SPY" and snap["cached"] is False and n["calls"] == 5
    assert snap["latest"]["close"] == 600.0 and snap["valuation"] is None and "404" in snap["errors"]["valuation"]
    assert snap["short_interest"] == [{"x": 1}] and snap["ownership"]["institutional"]["percentOutstanding"] == 50.0
    assert eq.company("SPY")["cached"] is True and n["calls"] == 5          # served from the 6-hour cache
    eq.company("SPY", refresh=True)
    assert n["calls"] == 10

    def denied(path, params=None):
        raise P.EquiblesError("Equibles 401: API key rejected", 401)
    monkeypatch.setattr(eq, "_get", denied)
    with pytest.raises(P.EquiblesError):
        eq.company("AAPL")


def test_key_is_saved_masked_and_enables_the_source(client):
    _set_key(client, None)
    assert not P.PROVIDERS["equibles"].available()
    assert client.get("/api/data/company/AAPL").status_code == 400          # not connected yet
    _set_key(client)
    assert get_settings().equibles_api_key == KEY
    body = client.get("/api/integrations").text
    assert KEY not in body
    card = next(i for i in client.get("/api/integrations").json() if i["key"] == "equibles")
    assert card["configured"] and card["editable"][0]["current"] == "eq_t...cdef"
    src = next(s for s in client.get("/api/data/sources").json() if s["name"] == "equibles")
    assert src["available"] is True
    _set_key(client, None)


def test_company_endpoint_returns_snapshot_and_maps_upstream_errors(client, monkeypatch):
    _set_key(client)
    eq = P.PROVIDERS["equibles"]
    monkeypatch.setattr(eq, "_company", {})
    monkeypatch.setattr(eq, "_get", lambda path, params=None: {"data": [], "meta": {"hasMore": False}})
    r = client.get("/api/data/company/NVDA")
    assert r.status_code == 200 and r.json()["symbol"] == "NVDA"

    def limited(path, params=None):
        raise P.EquiblesError("Equibles 429: daily request limit reached", 429)
    monkeypatch.setattr(eq, "_get", limited)
    r = client.get("/api/data/company/NVDA?refresh=true")
    assert r.status_code == 502 and "limit" in r.json()["detail"]
    _set_key(client, None)
