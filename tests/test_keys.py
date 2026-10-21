"""API keys pasted into the Integrations page: saved to <DATA_DIR>/keys.env, used at once, never echoed."""
import os
import stat

from trader.config import get_settings, keys_file


def _clear(client):
    client.put("/api/integrations/alpaca/keys", json={"clear": ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_DATA_FEED"]})


def test_save_alpaca_keys_is_used_at_once_and_masked(client):
    _clear(client)
    assert get_settings().alpaca_configured is False
    r = client.put("/api/integrations/alpaca/keys",
                   json={"values": {"APCA_API_KEY_ID": "PKTESTKEY1234567890", "APCA_API_SECRET_KEY": "s3cretVALUE0987654321"}})
    assert r.status_code == 200, r.text
    body = r.text
    assert "PKTESTKEY1234567890" not in body and "s3cretVALUE0987654321" not in body      # never echoed
    s = get_settings()                                    # no restart: settings re-read from keys.env
    assert s.alpaca_configured and s.alpaca_key_id == "PKTESTKEY1234567890"
    card = next(i for i in client.get("/api/integrations").json() if i["key"] == "alpaca")
    assert card["configured"] is True
    f = {x["name"]: x for x in card["editable"]}
    assert f["APCA_API_KEY_ID"]["current"] == "PKTE...7890" and f["APCA_API_KEY_ID"]["saved_in_app"]
    assert "s3cretVALUE0987654321" not in client.get("/api/integrations").text
    mode = stat.S_IMODE(os.stat(keys_file()).st_mode)
    assert mode == 0o600                                  # private to the user
    _clear(client)
    assert get_settings().alpaca_configured is False


def test_blank_keeps_value_and_select_is_validated(client):
    _clear(client)
    client.put("/api/integrations/alpaca/keys", json={"values": {"APCA_API_KEY_ID": "PKKEEPME00000000"}})
    client.put("/api/integrations/alpaca/keys", json={"values": {"APCA_API_KEY_ID": "", "APCA_DATA_FEED": "sip"}})
    s = get_settings()
    assert s.alpaca_key_id == "PKKEEPME00000000" and s.alpaca_data_feed == "sip"
    assert client.put("/api/integrations/alpaca/keys", json={"values": {"APCA_DATA_FEED": "live"}}).status_code == 400
    _clear(client)


def test_rejects_unknown_names_and_bad_values(client):
    # only the integration's own allow-listed names
    r = client.put("/api/integrations/alpaca/keys", json={"values": {"DATABASE_URL": "sqlite:///x.db"}})
    assert r.status_code == 400
    r = client.put("/api/integrations/database/keys", json={"values": {"DATABASE_URL": "sqlite:///x.db"}})
    assert r.status_code == 400
    # no newline / injection into the env file
    r = client.put("/api/integrations/newsapi/keys", json={"values": {"NEWSAPI_KEY": "abc\nAPCA_API_KEY_ID=evil"}})
    assert r.status_code == 400
    r = client.put("/api/integrations/newsapi/keys", json={"values": {"NEWSAPI_KEY": "has space"}})
    assert r.status_code == 400
    assert "evil" not in (keys_file().read_text() if keys_file().exists() else "")


def test_saved_key_beats_env_var(client, monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "fromenv0000000000")
    from trader.config import reset_settings
    reset_settings()
    assert get_settings().newsapi_key == "fromenv0000000000"
    client.put("/api/integrations/newsapi/keys", json={"values": {"NEWSAPI_KEY": "fromapp1111111111"}})
    assert get_settings().newsapi_key == "fromapp1111111111"
    client.put("/api/integrations/newsapi/keys", json={"clear": ["NEWSAPI_KEY"]})
    assert get_settings().newsapi_key == "fromenv0000000000"
