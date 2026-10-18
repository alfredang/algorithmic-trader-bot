"""TradingView webhook: alert -> validate -> signal confirmation -> risk -> paper order (course Lab 17).

TradingView alert message (paste into the alert's Message box; placeholders are filled by TradingView):
  {"secret": "<your secret>", "id": "{{timenow}}-{{strategy.order.id}}", "ticker": "{{ticker}}",
   "action": "{{strategy.order.action}}", "qty": "{{strategy.order.contracts}}", "price": "{{close}}"}
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.broker import service as BRK
from trader.config import get_settings, mask
from trader.data import service as data
from trader.models import Bot, Setting, WebhookAlert
from trader.services.events import emit, stage
from trader.strategies import registry

DEFAULTS = {"require_signal_agreement": False, "strategy_key": "ema_cross", "params": {}, "max_order_qty": 100,
            "allowed_symbols": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "JPM", "XLF", "GLD", "TLT", "KO", "PEP", "BAC"],
            "account": "TradingView webhook account", "bot_id": None}


def config(db: Session) -> dict:
    s = db.get(Setting, "webhook")
    return {**DEFAULTS, **((s.value if s else None) or {})}


def secret(db: Session) -> tuple[str, str]:
    """(secret, source). WEBHOOK_SECRET from .env wins; otherwise a random secret generated once and kept locally."""
    env = get_settings().webhook_secret
    if env:
        return env, "env"
    s = db.get(Setting, "webhook_secret_generated")
    if s is None or not s.value:
        s = Setting(key="webhook_secret_generated", value=secrets.token_urlsafe(24))
        db.add(s)
        db.flush()
    return str(s.value), "generated"


def template(db: Session, reveal: bool = False) -> dict:
    sec, src = secret(db)
    shown = sec if reveal else mask(sec)
    msg = {"secret": shown, "id": "{{timenow}}-{{strategy.order.id}}", "ticker": "{{ticker}}",
           "action": "{{strategy.order.action}}", "qty": "{{strategy.order.contracts}}", "price": "{{close}}"}
    return {"message": json.dumps(msg, indent=2), "secret_source": src, "secret_masked": mask(sec),
            "path": "/api/webhooks/tradingview", "config": config(db),
            "notes": ["TradingView webhooks need a paid plan with two-factor authentication.",
                      "TradingView only posts to ports 80/443: expose the app with an HTTPS tunnel (e.g. ngrok http 8000) "
                      "and use https://<tunnel>/api/webhooks/tradingview as the Webhook URL.",
                      "Retries are safe: a repeated alert id is ignored (idempotent)."]}


def _signal(db: Session, ticker: str, cfg: dict) -> int | None:
    try:
        key, params = cfg["strategy_key"], cfg.get("params") or {}
        if cfg.get("bot_id"):
            bot = db.get(Bot, int(cfg["bot_id"]))
            if bot:
                key, params = bot.strategy_key, bot.params
        desc = registry.get(db, key)
        if desc["multi_asset"]:
            return None
        bars = data.load_bars(db, ticker)
        sig, _ = registry.compute_signals(db, key, bars, params)
        return int(round(float(sig.iloc[-1])))
    except Exception:
        return None


def handle(db: Session, payload, client: str = "", raw: bytes | None = None, session_override: str | None = None
           ) -> tuple[int, dict]:
    cfg = config(db)
    sec, _ = secret(db)
    rec = WebhookAlert(client=client[:64])
    db.add(rec)
    if not isinstance(payload, dict):
        code, body = 400, {"result": "rejected", "detail": "body is not a JSON object"}
        return _finish(db, rec, code, body, {"raw": (raw or b"")[:200].decode(errors="replace")})
    safe = {k: ("***" if k == "secret" else v) for k, v in payload.items()}
    if not hmac.compare_digest(str(payload.get("secret", "")), sec):
        return _finish(db, rec, 401, {"result": "rejected", "detail": "bad or missing secret"}, safe)
    ticker = str(payload.get("ticker", "")).upper().split(":")[-1]
    action = str(payload.get("action", "")).lower()
    rec.ticker, rec.action = ticker, action
    allowed = [s.upper() for s in cfg["allowed_symbols"]]
    if allowed and ticker not in allowed:
        return _finish(db, rec, 422, {"result": "rejected", "detail": f"{ticker or '?'} not on the allow-list"}, safe)
    if action not in ("buy", "sell"):
        return _finish(db, rec, 422, {"result": "rejected", "detail": f"unknown action '{action}'"}, safe)
    try:
        qty = float(payload.get("qty", 0))
    except (TypeError, ValueError):
        return _finish(db, rec, 422, {"result": "rejected", "detail": "qty is not a number"}, safe)
    rec.qty = qty
    if not 0 < qty <= float(cfg["max_order_qty"]):
        return _finish(db, rec, 422, {"result": "rejected", "detail": f"qty must be between 0 and {cfg['max_order_qty']}"}, safe)
    alert_id = str(payload.get("id") or hashlib.sha1(json.dumps(
        {k: payload.get(k) for k in ("ticker", "action", "qty", "time")}, sort_keys=True).encode()).hexdigest()[:16])
    rec.alert_id = alert_id[:128]
    seen = db.scalar(select(WebhookAlert.id).where(WebhookAlert.alert_id == rec.alert_id, WebhookAlert.http_status == 200,
                                                   WebhookAlert.result.in_(["order submitted", "no order needed"])))
    if seen:
        return _finish(db, rec, 200, {"result": "duplicate ignored", "alert_id": alert_id,
                                      "detail": "alert already processed (TradingView retries are safe)"}, safe)
    sig = _signal(db, ticker, cfg)
    rec.pipeline_signal = sig
    agrees = sig is None or (sig > 0) == (action == "buy")
    stage("signals", "ok" if agrees else "warning", f"TradingView {action} {ticker}: pipeline signal {sig} "
          f"({'agrees' if agrees else 'disagrees'})", {"ticker": ticker, "signal": sig}, db=db)
    if cfg["require_signal_agreement"] and not agrees:
        return _finish(db, rec, 409, {"result": "rejected", "alert_id": alert_id, "pipeline_signal": sig,
                                      "detail": f"pipeline signal for {ticker} is {sig}: it disagrees with the alert"}, safe)
    acct = BRK.get_account(db, cfg["account"])
    req = BRK.OrderRequest(symbol=ticker, side=action, qty=qty, type="auto",
                           client_order_id=BRK.client_id(f"tv{hashlib.sha1(alert_id.encode()).hexdigest()[:10]}", ticker,
                                                         action, qty), note=f"TradingView alert {alert_id}")
    r = BRK.place_order(db, acct, req, source="webhook", bot_id=cfg.get("bot_id"),
                        limits={"allowed_symbols": allowed, "max_order_qty": cfg["max_order_qty"]},
                        session_override=session_override)
    if not r["ok"]:
        code = 423 if r["risk"]["reason"] else 502
        return _finish(db, rec, code, {"result": "blocked by risk", "alert_id": alert_id, "pipeline_signal": sig,
                                       "detail": r["risk"]["reason"], "checks": r["risk"]["checks"]}, safe)
    o = r["order"]
    rec.order_id = o["id"]
    return _finish(db, rec, 200, {"result": "order submitted", "alert_id": alert_id, "pipeline_signal": sig,
                                  "signal_agrees": agrees, "order_id": o["id"], "status": o["status"], "symbol": ticker,
                                  "side": o["side"], "qty": o["qty"], "type": o["type"], "session": r["session"]["session"],
                                  "filled_avg_price": o["filled_avg_price"]}, safe)


def _finish(db: Session, rec: WebhookAlert, code: int, body: dict, payload: dict) -> tuple[int, dict]:
    rec.http_status, rec.result, rec.detail, rec.payload = code, body.get("result", ""), str(body.get("detail", ""))[:2000], payload
    db.flush()
    emit("webhook.alert", {"id": rec.id, "http": code, "result": rec.result, "ticker": rec.ticker}, db=db)
    stage("webhook", "ok" if code == 200 else "warning", f"Alert {rec.ticker or '?'} {rec.action or ''}: HTTP {code} "
          f"{rec.result}", {"http": code}, db=db)
    return code, body


def test_alerts(sec: str) -> list[tuple[str, object, int]]:
    """The Lab 17 self-test: what TradingView sends, plus the expected HTTP code."""
    return [
        ("1. valid BUY 5 SPY", {"secret": sec, "id": "t1", "ticker": "SPY", "action": "buy", "qty": "5"}, 200),
        ("2. valid SELL 5 SPY", {"secret": sec, "id": "t2", "ticker": "AMEX:SPY", "action": "sell", "qty": "5"}, 200),
        ("3. wrong secret", {"secret": "guess", "id": "t3", "ticker": "SPY", "action": "buy", "qty": "5"}, 401),
        ("4. symbol not allowed", {"secret": sec, "id": "t4", "ticker": "TSLA", "action": "buy", "qty": "5"}, 422),
        ("5. qty above limit", {"secret": sec, "id": "t5", "ticker": "AAPL", "action": "buy", "qty": "5000"}, 422),
        ("6. malformed message", "ticker=SPY action=buy", 400),
        ("7. TradingView retry of alert 1", {"secret": sec, "id": "t1", "ticker": "SPY", "action": "buy", "qty": "5"}, 200),
    ]
