"""Reddit posts about a stock (News Sentiment agent input).

Auth: Reddit's OAuth2 "application-only" flow with client credentials - no Reddit user login.
  1. POST https://www.reddit.com/api/v1/access_token  (HTTP Basic auth = client id / secret,
     grant_type=client_credentials)  ->  bearer token valid for about an hour (cached here)
  2. GET  https://oauth.reddit.com/r/<sub>/search?q=<symbol or company>&restrict_sr=1&sort=new&t=week
Keys: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (reddit.com/prefs/apps -> "create another app" -> type
"script"), REDDIT_USER_AGENT (Reddit asks for a unique, descriptive one) and REDDIT_SUBREDDITS.

Posts are untrusted text: they are only ever scored with the lexicon or handed to an LLM as DATA.
Without keys every function degrades gracefully (``configured: False``, no posts) so the app stays offline-capable.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import UTC, datetime

import httpx

from trader.config import get_settings
from trader.sentiment.news import score

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
CACHE_TTL_S = 15 * 60                 # posts per (symbol, subreddits) are cached 15 minutes
MAX_TEXT = 500

_lock = threading.Lock()
_token: dict = {"value": None, "expires": 0.0, "client": None}
_cache: dict[tuple, tuple[float, dict]] = {}


class RedditError(RuntimeError):
    pass


def _client() -> httpx.Client:
    """HTTP client factory (tests replace it with an httpx.MockTransport client - no network in tests)."""
    return httpx.Client(timeout=15)


def subreddits(value: str | None = None) -> list[str]:
    raw = value if value is not None else get_settings().reddit_subreddits
    return [s.strip().removeprefix("r/") for s in (raw or "").split(",") if s.strip()][:8]


def _headers() -> dict:
    return {"User-Agent": get_settings().reddit_user_agent or "python:algorithmic-trader-bot:v2"}


def access_token(client: httpx.Client, force: bool = False) -> str:
    s = get_settings()
    if not s.reddit_configured:
        raise RedditError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not set - add them on the Integrations page")
    with _lock:
        if not force and _token["value"] and _token["client"] == s.reddit_client_id and time.time() < _token["expires"] - 60:
            return _token["value"]
    r = client.post(TOKEN_URL, auth=(s.reddit_client_id, s.reddit_client_secret),
                    data={"grant_type": "client_credentials"}, headers=_headers())
    if r.status_code == 401:
        raise RedditError("Reddit rejected the client id / secret (HTTP 401)")
    if r.status_code >= 400:
        raise RedditError(f"Reddit token request failed: HTTP {r.status_code} {r.text[:200]}")
    js = r.json()
    if "access_token" not in js:
        raise RedditError(f"Reddit token error: {js.get('error', js)}")
    with _lock:
        _token.update(value=js["access_token"], expires=time.time() + float(js.get("expires_in", 3600)),
                      client=s.reddit_client_id)
    return js["access_token"]


def _query(symbol: str, company: str | None) -> str:
    q = f'"{symbol}"'
    if company and company.upper() != symbol.upper():
        q += f' OR "{company}"'
    return q


def parse(js: dict, symbol: str) -> list[dict]:
    """Reddit Listing JSON -> post dicts with a lexicon sentiment score (no author names kept)."""
    out = []
    for ch in ((js or {}).get("data") or {}).get("children") or []:
        d = ch.get("data") or {}
        title = (d.get("title") or "").strip()
        if not title:
            continue
        body = (d.get("selftext") or "").strip()[:MAX_TEXT]
        created = datetime.fromtimestamp(float(d.get("created_utc") or 0), UTC)
        out.append({"symbol": symbol, "id": d.get("id"), "subreddit": d.get("subreddit"), "title": title[:300],
                    "text": body, "upvotes": int(d.get("score") or 0), "comments": int(d.get("num_comments") or 0),
                    "created_at": created.isoformat(timespec="seconds"),
                    "url": f"https://www.reddit.com{d.get('permalink', '')}" if d.get("permalink") else "",
                    "lexicon_score": round(score(f"{title}. {body[:300]}"), 3)})
    return out


def search(symbol: str, company: str | None = None, subs: list[str] | None = None, limit: int = 15,
           client: httpx.Client | None = None) -> dict:
    """Recent posts (last week, newest first) mentioning the symbol or company in each subreddit."""
    symbol = symbol.upper().strip()
    subs = subs or subreddits()
    own = client is None
    client = client or _client()
    posts, errors = [], {}
    try:
        token = access_token(client)
        for sub in subs:
            r = client.get(f"{API}/r/{sub}/search", headers={**_headers(), "Authorization": f"bearer {token}"},
                           params={"q": _query(symbol, company), "restrict_sr": 1, "sort": "new", "t": "week",
                                   "limit": min(int(limit), 100), "raw_json": 1})
            if r.status_code >= 400:
                errors[sub] = f"HTTP {r.status_code}"
                continue
            posts += parse(r.json(), symbol)
    finally:
        if own:
            client.close()
    seen, uniq = set(), []
    for p in sorted(posts, key=lambda p: p["created_at"], reverse=True):
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        uniq.append(p)
    return {"symbol": symbol, "source": "reddit", "configured": True, "subreddits": subs, "posts": uniq,
            "errors": errors, "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"), "cached": False}


def posts(symbol: str, company: str | None = None, subs: list[str] | None = None, limit: int = 15,
          refresh: bool = False) -> dict:
    """Cached :func:`search`. Without keys returns an empty, clearly labelled result instead of raising."""
    symbol = symbol.upper().strip()
    subs = subs or subreddits()
    if not get_settings().reddit_configured:
        return {"symbol": symbol, "source": "reddit", "configured": False, "subreddits": subs, "posts": [],
                "errors": {}, "cached": False,
                "note": "Reddit is not connected - add REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET on the Integrations page"}
    key = (symbol, tuple(subs), int(limit))
    hit = _cache.get(key)
    if hit and not refresh and time.time() - hit[0] < CACHE_TTL_S:
        return {**hit[1], "cached": True}
    out = search(symbol, company, subs, limit)
    _cache[key] = (time.time(), out)
    return out


def summarise(items: list[dict]) -> dict:
    """Upvote-weighted lexicon average: weight = 1 + log(1 + upvotes)."""
    if not items:
        return {"score": 0.0, "n": 0}
    w = [1 + math.log1p(max(p.get("upvotes", 0), 0)) for p in items]
    s = sum(p["lexicon_score"] * wi for p, wi in zip(items, w, strict=True)) / sum(w)
    return {"score": round(s, 3), "n": len(items)}


def reddit_test() -> dict:
    """Integrations page 'Test connection': fetch a token and one search result (2 requests)."""
    with _client() as c:
        access_token(c, force=True)
        sub = (subreddits() or ["stocks"])[0]
        res = search("SPY", None, [sub], limit=1, client=c)
    return {"token": "ok", "subreddit": sub, "posts": len(res["posts"]), "errors": res["errors"]}


def clear_cache() -> None:
    _cache.clear()
    _token.update(value=None, expires=0.0, client=None)
