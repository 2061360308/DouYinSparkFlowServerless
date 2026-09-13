from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from tortoise import connections

from server.deps import get_settings
from server.routers import accounts, account_scan, admin, auth, dashboard, internal, runs, tasks, install
from server.schemas import HealthResponse
from core.config import Settings
from core.services import Conflict, NotFound, ValidationError
from core.db.connection import close_persistent, open_persistent

logger = logging.getLogger(__name__)

_ERROR_STATUS = {NotFound: 404, Conflict: 409, ValidationError: 400}


async def _bootstrap_admin(settings: Settings) -> None:
    """serverless 首次引导：配置了 SPARK_ADMIN_USERNAME/SPARK_ADMIN_PASSWORD 且数据库
    尚无任何管理员时，自动创建首个管理员（登录后强制改密）。已存在管理员则跳过。
    """
    from core.db.models import User
    from core.security import PasswordService
    from core.services.users import UserService

    if not (settings.admin_username and settings.admin_password):
        return
    if await User.filter(role="admin").exists():
        return
    try:
        await UserService(PasswordService()).create(
            settings.admin_username, settings.admin_password, role="admin"
        )
    except Exception as error:  # noqa: BLE001 - 引导失败不影响服务启动，仅记录
        logger.warning("admin bootstrap skipped: %s", error)
        return
    logger.info("bootstrap admin created: %s", settings.admin_username)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动即建立并钉住数据库连接（serverless 冷启动一次，后续请求复用）
    settings = get_settings()
    await open_persistent()
    try:
        # serverless 无 CLI：幂等确保表结构/索引/默认配置就绪
        from core.db.init_db import init_objects
        await init_objects()
        await _bootstrap_admin(settings)
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

    @app.get("/api/health/live", response_model=HealthResponse)
    async def live() -> dict:
        return {"status": "ok"}

    @app.get("/api/health/ready", response_model=HealthResponse)
    async def ready() -> dict:
        conn = connections.get("default")
        await conn.execute_query("SELECT 1")
        return {"status": "ready"}

    for module in (auth, accounts, account_scan, tasks, runs, dashboard, admin, internal, install):
        app.include_router(module.router)

    return app
