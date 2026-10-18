"""FastAPI application: REST API under /api, OpenAPI docs at /docs, the static SPA at /."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from trader import __version__
from trader.api.routers import agents, backtests, data, strategies, system, trading
from trader.config import ROOT, WEB_DIR, get_settings

log = logging.getLogger("trader")

DESCRIPTION = """Quant / algorithmic trading simulator - companion software for the IBF course
**Machine Learning 101 for Financial Trading** (Tertiary Infotech Academy).

**PAPER TRADING ONLY.** There is no live-money order path: Alpaca is always used with `paper=True`
and the built-in simulator broker is used when no keys are configured. Not investment advice.
"""


def create_app(start_worker: bool | None = None, migrate: bool = True) -> FastAPI:
    s = get_settings()
    worker_holder = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if migrate:
            from trader.db import migrate as do_migrate
            do_migrate()
        if s.auto_seed:
            from trader.db import session_scope
            from trader.models import Bar
            with session_scope() as db:
                if db.query(Bar.id).first() is None:
                    from trader.services.seed import seed
                    seed(db, log_fn=log.info)
        if start_worker if start_worker is not None else s.run_scheduler_in_process:
            from trader.scheduler import Worker
            w = Worker()
            w.start()
            worker_holder["w"] = w
            log.info("in-process scheduler started")
        yield
        if "w" in worker_holder:
            worker_holder["w"].shutdown()

    app = FastAPI(title="Quant Trading Simulator API", version=__version__, description=DESCRIPTION, lifespan=lifespan,
                  docs_url="/docs", redoc_url="/redoc", openapi_url="/api/openapi.json")
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",")],
                           allow_methods=["*"], allow_headers=["*"])
    @app.middleware("http")
    async def no_stale_static(request, call_next):
        resp = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path == "/":
            resp.headers["Cache-Control"] = "no-cache"          # revalidate (ETag) so upgrades show at once
        return resp

    for r in (system.router, data.router, strategies.router, backtests.router, trading.router, agents.router):
        app.include_router(r)

    @app.exception_handler(Exception)
    async def unhandled(request, exc):           # pragma: no cover - last-resort JSON error
        log.exception("unhandled error")
        return JSONResponse({"detail": f"{type(exc).__name__}: {str(exc)[:300]}"}, status_code=500)

    if s.serve_frontend and WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(WEB_DIR / "index.html")

        @app.get("/favicon.ico", include_in_schema=False)
        def favicon():
            return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml")

    guide = ROOT / "docs" / "USER_GUIDE.md"

    @app.get("/guide.md", include_in_schema=False)
    def user_guide():
        if not guide.exists():
            return PlainTextResponse("# User guide\n\nSee docs/USER_GUIDE.md in the repository.", media_type="text/markdown")
        return PlainTextResponse(guide.read_text(encoding="utf-8"), media_type="text/markdown")

    shots = ROOT / "docs" / "screenshots"
    if shots.exists():
        app.mount("/screenshots", StaticFiles(directory=shots), name="screenshots")
    return app
