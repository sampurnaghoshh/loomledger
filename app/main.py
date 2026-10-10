"""FastAPI application: `uvicorn app.main:app --reload --port 8000` (docs at /docs)."""
from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import auth, realtime
from app.config import get_settings
from app.db import create_pool
from app.modules.finance import router as finance
from app.modules.floor import router as floor
from app.modules.inventory import router as inventory
from app.modules.orders import router as orders
from app.modules.production import router as production
from app.modules.quality import router as quality
from app.modules.recalls import router as recalls
from app.modules.trace import router as trace
from app.modules.workforce import router as workforce
from app.errors import handle_unexpected, install_exception_handlers

log = logging.getLogger("loomledger.request")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    pool = create_pool(settings.DATABASE_URL)
    pool.open(wait=False)          # start even if the DB is down; /api/health reports it
    app.state.pool = pool

    broadcaster = realtime.Broadcaster()
    listener = realtime.FloorListener(settings.DATABASE_URL, broadcaster.publish)
    app.state.floor_broadcaster = broadcaster
    app.state.floor_listener = listener
    await listener.start()
    try:
        yield
    finally:
        await listener.stop()
        pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = FastAPI(title="LoomLedger API", version="0.1.0", lifespan=lifespan)
    install_exception_handlers(app)

    @app.middleware("http")
    async def request_id_and_log(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 — anything not handled below becomes a clean 500
            response = handle_unexpected(request, exc)
        ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = rid
        log.info("rid=%s %s %s %s %.1fms", rid, request.method, request.url.path, response.status_code, ms)
        return response

    # CORS is added last so it wraps everything, including error responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.get("/api/health", tags=["platform"])
    def health(request: Request) -> JSONResponse:
        try:
            with request.app.state.pool.connection(timeout=2) as conn:
                conn.execute("SELECT 1").fetchone()
            listening = request.app.state.floor_listener.connected.is_set()
            return JSONResponse({"status": "ok", "db": "ok", "realtime": "ok" if listening else "connecting"})
        except Exception:  # noqa: BLE001
            log.warning("health: database unreachable rid=%s", request.state.request_id)
            return JSONResponse({"status": "degraded", "db": "fail", "realtime": "connecting"}, status_code=503)

    app.include_router(auth.router)
    app.include_router(realtime.router)          # WS /ws/floor

    # ---- AREA ROUTERS ---------------------------------------------------------------------------
    # Each area lives in app/modules/<area>/ (router -> service -> repository). Include them here:
    app.include_router(floor.router)
    app.include_router(inventory.router)
    app.include_router(production.router)
    app.include_router(quality.router)
    app.include_router(orders.router)            # /api/orders, /api/dispatches, /api/track (public)
    app.include_router(finance.router)
    app.include_router(trace.router)
    app.include_router(recalls.router)
    app.include_router(workforce.router)
    # ---------------------------------------------------------------------------------------------

    return app


app = create_app()
