from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from tortoise import connections

from server.deps import get_settings
from server.routers import accounts, admin, auth, dashboard, runs, tasks
from core.services import Conflict, NotFound, ValidationError
from core.db.connection import close_persistent, open_persistent

_ERROR_STATUS = {NotFound: 404, Conflict: 409, ValidationError: 400}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动即建立并钉住数据库连接（serverless 冷启动一次，后续请求复用）
    await open_persistent()
    try:
        yield
    finally:
        await close_persistent()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="DouyinSpark Console API", lifespan=lifespan)

    if settings.dev_insecure:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(NotFound)
    @app.exception_handler(Conflict)
    @app.exception_handler(ValidationError)
    async def _service_error(_request: Request, exc: Exception) -> JSONResponse:
        status = _ERROR_STATUS.get(type(exc), 400)
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.get("/api/health/live")
    async def live() -> dict:
        return {"status": "ok"}

    @app.get("/api/health/ready")
    async def ready() -> dict:
        conn = connections.get("default")
        await conn.execute_query("SELECT 1")
        return {"status": "ready"}

    for module in (auth, accounts, tasks, runs, dashboard, admin):
        app.include_router(module.router)

    return app
