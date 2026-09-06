"""FastAPI 依赖：配置/服务单例、会话鉴权、CSRF、管理员守卫。"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException, Request

from core.config import Settings
from core.crypto import CookieCipher
from core.security import PasswordService, SessionService
from core.services.auth import AuthService
from core.db.models import User, WebSession

SESSION_COOKIE = "spark_session"


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


@dataclass
class Services:
    settings: Settings
    passwords: PasswordService
    sessions: SessionService
    cookie_cipher: CookieCipher
    auth: AuthService


@lru_cache
def get_services() -> Services:
    settings = get_settings()
    passwords = PasswordService()
    sessions = SessionService(settings.session_key)
    cookie_cipher = CookieCipher(settings.cookie_key)
    auth = AuthService(sessions, passwords)
    return Services(settings, passwords, sessions, cookie_cipher, auth)


@dataclass
class AuthContext:
    user: User
    record: WebSession


async def _load(request: Request) -> AuthContext | None:
    raw = request.cookies.get(SESSION_COOKIE)
    loaded = await get_services().auth.load(raw)
    if loaded is None:
        return None
    user, record = loaded
    return AuthContext(user=user, record=record)


async def current_allow_change(request: Request) -> AuthContext:
    ctx = await _load(request)
    if ctx is None:
        raise HTTPException(401, "authentication required")
    return ctx


async def current_user(request: Request) -> AuthContext:
    ctx = await current_allow_change(request)
    if ctx.user.must_change_password:
        raise HTTPException(409, "password-change-required")
    return ctx


async def require_admin(ctx: AuthContext = Depends(current_user)) -> AuthContext:
    if ctx.user.role != "admin":
        raise HTTPException(404, "not found")
    return ctx


def _check_csrf(request: Request, ctx: AuthContext) -> None:
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not secrets.compare_digest(ctx.record.csrf_token, supplied):
        raise HTTPException(403, "CSRF validation failed")


async def user_csrf(request: Request, ctx: AuthContext = Depends(current_user)) -> AuthContext:
    """需要登录 + CSRF 的写操作依赖。"""
    _check_csrf(request, ctx)
    return ctx


async def user_csrf_allow_change(
    request: Request, ctx: AuthContext = Depends(current_allow_change)
) -> AuthContext:
    """允许未改密用户 + CSRF（用于修改密码接口）。"""
    _check_csrf(request, ctx)
    return ctx


async def admin_csrf(request: Request, ctx: AuthContext = Depends(require_admin)) -> AuthContext:
    """需要管理员 + CSRF 的写操作依赖。"""
    _check_csrf(request, ctx)
    return ctx


async def require_service(request: Request) -> None:
    """机器身份守卫：校验服务令牌（供任务函数访问 /api/internal/*）。

    令牌来自 Settings.service_token（环境变量 SPARK_SERVICE_TOKEN）。未配置则一律拒绝。
    请求头：``Authorization: Bearer <token>`` 或 ``X-Service-Token: <token>``。
    """
    expected = get_settings().service_token
    if not expected:
        raise HTTPException(503, "internal API disabled (SPARK_SERVICE_TOKEN unset)")
    supplied = request.headers.get("x-service-token", "")
    if not supplied:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, "invalid service token")
