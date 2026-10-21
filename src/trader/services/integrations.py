"""Integration status (secrets always masked) and test-connection checks."""
from __future__ import annotations

import re
import shutil
import subprocess

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trader.agents import providers as AIP
from trader.config import get_settings, mask
from trader.models import WebhookAlert


def _db_url_masked(url: str) -> str:
    return re.sub(r"//([^:/@]+):([^@]+)@", lambda m: f"//{m.group(1)}:***@", url)


def status(db: Session) -> list[dict]:
    return _with_forms(_status(db))


def _status(db: Session) -> list[dict]:
    s = get_settings()
    from trader.services import webhook as WH
    sec, src = WH.secret(db)
    claude_cli = shutil.which("claude")
    codex = AIP.codex_login_status()
    return [
        {"key": "alpaca", "name": "Alpaca (paper trading + market data + news)", "configured": s.alpaca_configured,
         "fields": {"APCA_API_KEY_ID": mask(s.alpaca_key_id), "APCA_API_SECRET_KEY": mask(s.alpaca_secret_key),
                    "APCA_DATA_FEED": s.alpaca_data_feed},
         "mode": "paper=True (hard-coded - no live trading)",
         "help": "app.alpaca.markets -> switch to your Paper account -> Home -> API Keys -> Generate New Keys. "
                 "Paste the Key ID and Secret below and press Save. Without keys the built-in simulator broker "
                 "and the offline demo data are used.",
         "testable": s.alpaca_configured},
        {"key": "twelvedata", "name": "Twelve Data (time series)", "configured": bool(s.twelvedata_api_key),
         "fields": {"TWELVEDATA_API_KEY": mask(s.twelvedata_api_key)},
         "help": "Optional. twelvedata.com -> sign up (free) -> API keys; paste it below. Used when you pick "
                 "'Twelve Data' as the source on the Data page.",
         "testable": bool(s.twelvedata_api_key)},
        {"key": "newsapi", "name": "NewsAPI.org (headlines)", "configured": bool(s.newsapi_key),
         "fields": {"NEWSAPI_KEY": mask(s.newsapi_key)},
         "help": "Optional. newsapi.org -> Get API key (free Developer plan: development only, 24 h delay, 100 "
                 "requests/day, articles up to a month old); paste it below.",
         "testable": bool(s.newsapi_key)},
        {"key": "yfinance", "name": "Yahoo Finance via yfinance (fallback)", "configured": True, "fields": {},
         "help": "No key needed. For personal / educational use only; not for redistribution.", "testable": True},
        {"key": "tradingview", "name": "TradingView webhook", "configured": True,
         "fields": {"WEBHOOK_SECRET": mask(sec), "source": "from .env" if src == "env" else "generated locally"},
         "alerts": int(db.scalar(select(func.count(WebhookAlert.id))) or 0),
         "help": "Alerts POST to /api/webhooks/tradingview. Needs a paid TradingView plan and a public HTTPS URL "
                 "(tunnel). The self-test works without TradingView.", "testable": True},
        {"key": "codex", "name": "OpenAI Codex - Sign in with ChatGPT (subscription, primary)",
         "configured": bool(codex.get("logged_in")),
         "fields": {"login": codex.get("detail") or ("logged in" if codex.get("logged_in") else "not logged in"),
                    "CODEX_MODEL": s.codex_model or "(Codex default)"},
         "login_command": AIP.TERMS["codex"]["login_command"], "terms": AIP.TERMS["codex"],
         "help": "Install the Codex CLI or `uv sync --extra ai` (bundles it), run `codex login` and choose Sign in with "
                 "ChatGPT. The app only asks Codex whether you are logged in; it never reads or stores tokens.",
         "testable": True},
        {"key": "claude", "name": "Claude (Claude Agent SDK, API key)", "configured": bool(s.anthropic_api_key),
         "fields": {"ANTHROPIC_API_KEY": mask(s.anthropic_api_key), "CLAUDE_MODEL": s.claude_model,
                    "CLAUDE_MODEL_DEEP": s.claude_model_deep,
                    "claude_cli_detected": "yes (its subscription login is NOT used)" if claude_cli else "no"},
         "login_command": AIP.TERMS["claude"]["login_command"], "terms": AIP.TERMS["claude"],
         "help": "Claude.ai subscription login is not available: Anthropic's terms do not allow third-party apps to offer "
                 "it. Use an Anthropic API key (or Bedrock / Vertex AI credentials).", "testable": bool(s.anthropic_api_key)},
        {"key": "openai", "name": "OpenAI (OpenAI Agents SDK, API key)", "configured": bool(s.openai_api_key),
         "fields": {"OPENAI_API_KEY": mask(s.openai_api_key), "OPENAI_MODEL": s.openai_model or "(SDK default)"},
         "login_command": AIP.TERMS["openai"]["login_command"], "terms": AIP.TERMS["openai"],
         "help": "API-key auth for the Agents SDK (native agents-as-tools orchestration).",
         "testable": bool(s.openai_api_key)},
        {"key": "database", "name": "Database", "configured": True,
         "fields": {"DATABASE_URL": _db_url_masked(s.database_url)}, "help": "SQLite by default; Postgres in Docker Compose.",
         "testable": True},
    ]


def _with_forms(items: list[dict]) -> list[dict]:
    from trader.services import keys as K
    for it in items:
        it["editable"] = K.fields_for(it["key"])
    return items


def test(db: Session, key: str) -> dict:
    try:
        if key == "alpaca":
            from trader.broker.service import AlpacaPaperBroker, get_account
            br = AlpacaPaperBroker(db, get_account(db, "Alpaca paper account", broker="alpaca_paper"))
            info = br.account_info()
            clk = br.session()
            return {"ok": True, "message": f"Paper account {info['status']}, equity USD {info['equity']:,.2f}; "
                                           f"session {clk['session']}", "detail": {**info, "session": clk["session"]}}
        if key == "twelvedata":
            from trader.data.providers import PROVIDERS
            js = PROVIDERS["twelvedata"].test()
            return {"ok": True, "message": f"Twelve Data OK - usage {js.get('current_usage')}/{js.get('plan_limit')}",
                    "detail": js}
        if key == "newsapi":
            from trader.sentiment.news import newsapi_test
            return {"ok": True, "message": "NewsAPI OK", "detail": newsapi_test()}
        if key == "yfinance":
            from trader.data.providers import PROVIDERS
            df = PROVIDERS["yfinance"].bars("SPY", "1Day", start=None)
            return {"ok": True, "message": f"yfinance OK - SPY last close {df['close'].iloc[-1]:.2f} ({str(df.index[-1])[:10]})"}
        if key == "tradingview":
            from trader.services import webhook as WH
            sec, _ = WH.secret(db)
            results = []
            import uuid
            tag = uuid.uuid4().hex[:6]
            for title, body, expected in WH.test_alerts(sec):
                if isinstance(body, dict) and body.get("id"):
                    body = {**body, "id": f"{tag}-{body['id']}"}
                code, resp = WH.handle(db, body, client="self-test", raw=body.encode() if isinstance(body, str) else None,
                                       session_override="regular")
                results.append({"test": title, "http": code, "expected": expected, "ok": code == expected,
                                "result": resp.get("result"), "detail": resp.get("detail", "")})
            passed = sum(r["ok"] for r in results)
            return {"ok": passed == len(results), "message": f"{passed}/{len(results)} simulated alerts handled as expected",
                    "detail": results}
        if key in ("codex", "claude", "openai"):
            if key == "codex":
                AIP.codex_login_status(force=True)
            p = AIP.PROVIDERS[key]()
            ok, msg = p.available()
            return {"ok": ok, "message": msg, "detail": {"auth_mode": p.auth_mode, "model": p.model,
                                                         "note": "Availability check only - no model call is made."}}
        if key == "database":
            from sqlalchemy import text
            db.execute(text("SELECT 1"))
            return {"ok": True, "message": f"Connected ({db.bind.dialect.name})"}
        return {"ok": False, "message": f"unknown integration {key}"}
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:300]}"}


def claude_cli_version() -> str | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        return subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None
