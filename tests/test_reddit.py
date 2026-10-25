"""Reddit integration with the HTTP layer mocked (httpx.MockTransport) - no network."""
import httpx
import pytest

from trader.agents import tools as T
from trader.config import get_settings
from trader.sentiment import reddit as RD

ID, SECRET = "redditclientid123", "redditsecret456789"


def listing(*posts):
    return {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": p} for p in posts]}}


POST_A = {"id": "a1", "subreddit": "stocks", "title": "NVDA beats earnings, record data-center revenue", "selftext": "Strong quarter.",
          "score": 120, "num_comments": 40, "created_utc": 1767000000, "permalink": "/r/stocks/comments/a1/x/"}
POST_B = {"id": "b2", "subreddit": "investing", "title": "Worried about NVDA export restrictions and a probe", "selftext": "",
          "score": 3, "num_comments": 2, "created_utc": 1767100000, "permalink": "/r/investing/comments/b2/y/"}


@pytest.fixture()
def mock_reddit(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "www.reddit.com" and request.url.path == "/api/v1/access_token":
            if request.headers.get("authorization", "").startswith("Basic "):
                return httpx.Response(200, json={"access_token": "tok-123", "token_type": "bearer", "expires_in": 3600})
            return httpx.Response(401, json={"error": 401})
        if request.url.host == "oauth.reddit.com":
            assert request.headers["authorization"] == "bearer tok-123"
            assert request.url.params["restrict_sr"] == "1" and request.url.params["sort"] == "new"
            sub = request.url.path.split("/")[2]
            return httpx.Response(200, json=listing(POST_A, POST_B) if sub == "stocks" else listing(POST_B))
        return httpx.Response(404)
    monkeypatch.setattr(RD, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    RD.clear_cache()
    yield calls
    RD.clear_cache()


def _keys(client, on=True):
    names = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT", "REDDIT_SUBREDDITS"]
    if on:
        r = client.put("/api/integrations/reddit/keys", json={"values": {
            "REDDIT_CLIENT_ID": ID, "REDDIT_CLIENT_SECRET": SECRET,
            "REDDIT_USER_AGENT": "python:qts-test:v1 (by /u/tester)", "REDDIT_SUBREDDITS": "stocks, investing"}})
        assert r.status_code == 200, r.text
    else:
        client.put("/api/integrations/reddit/keys", json={"clear": names})


def test_parse_and_summarise():
    posts = RD.parse(listing(POST_A, {"id": "x", "title": ""}), "NVDA")
    assert len(posts) == 1 and posts[0]["lexicon_score"] > 0 and posts[0]["url"].startswith("https://www.reddit.com/r/stocks")
    assert "author" not in posts[0]
    s = RD.summarise(posts + RD.parse(listing(POST_B), "NVDA"))
    assert s["n"] == 2 and s["score"] > 0                      # upvote-weighted: the 120-upvote post dominates
    assert RD.summarise([]) == {"score": 0.0, "n": 0}
    assert RD.subreddits("r/stocks, wallstreetbets ,") == ["stocks", "wallstreetbets"]


def test_without_keys_degrades_gracefully(client):
    _keys(client, False)
    r = client.get("/api/reddit?symbol=NVDA")
    assert r.status_code == 200 and r.json()["configured"] is False and r.json()["posts"] == []
    card = next(i for i in client.get("/api/integrations").json() if i["key"] == "reddit")
    assert card["configured"] is False and {f["name"] for f in card["editable"]} >= {"REDDIT_CLIENT_ID", "REDDIT_SUBREDDITS"}
    assert T.gather_reddit("NVDA", "auto")["n"] == 0


def test_keys_endpoint_test_and_cache(client, mock_reddit):
    _keys(client)
    s = get_settings()
    assert s.reddit_configured and s.reddit_subreddits == "stocks, investing" and "(by /u/tester)" in s.reddit_user_agent
    body = client.get("/api/integrations").text
    assert ID not in body and SECRET not in body                            # secrets only ever masked
    t = client.post("/api/integrations/reddit/test").json()
    assert t["ok"] and "token issued" in t["message"]
    r = client.get("/api/reddit?symbol=nvda").json()
    assert r["configured"] and r["subreddits"] == ["stocks", "investing"] and r["cached"] is False
    assert [p["id"] for p in r["posts"]] == ["b2", "a1"]                     # newest first, de-duplicated
    assert r["summary"]["n"] == 2
    n = len(mock_reddit)
    assert client.get("/api/reddit?symbol=NVDA").json()["cached"] is True and len(mock_reddit) == n
    g = T.gather_reddit("NVDA", "auto")                                       # what the News Sentiment agent sees
    assert g["n"] == 2 and g["posts"][0]["subreddit"] in ("stocks", "investing")
    assert T.gather_reddit("NVDA", "offline")["n"] == 0                       # offline: never queried
    _keys(client, False)


def test_bad_values_and_rejected_credentials(client, monkeypatch):
    assert client.put("/api/integrations/reddit/keys", json={"values": {"REDDIT_USER_AGENT": 'x"; rm -rf'}}).status_code == 400
    assert client.put("/api/integrations/reddit/keys", json={"values": {"REDDIT_SUBREDDITS": "a\nAPCA_API_KEY_ID=x"}}).status_code == 400
    _keys(client)
    monkeypatch.setattr(RD, "_client", lambda: httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(401))))
    RD.clear_cache()
    t = client.post("/api/integrations/reddit/test").json()
    assert t["ok"] is False and "401" in t["message"]
    assert client.get("/api/reddit?symbol=NVDA&refresh=true").status_code == 502
    RD.clear_cache()
    _keys(client, False)
