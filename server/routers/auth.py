from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from server.deps import (
    SESSION_COOKIE,
    AuthContext,
    Services,
    current_allow_change,
    get_services,
    user_csrf_allow_change,
)
from core.services.users import UserService

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_MAX_AGE = 8 * 3600


class LoginBody(BaseModel):
    username: str
    password: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str
    new_password_confirmation: str = ""


def _user_dict(user) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


def _set_session_cookie(response: Response, raw: str, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


@router.post("/login")
async def login(
    body: LoginBody,
    response: Response,
    services: Services = Depends(get_services),
) -> dict:
    users = UserService(services.passwords)
    user = await users.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(400, "用户名或密码错误")
    raw, record = await services.auth.create_session(user.id)
    _set_session_cookie(response, raw, services.settings.secure_cookies)
    return {
        "csrf_token": record.csrf_token,
        "must_change_password": user.must_change_password,
        "user": _user_dict(user),
    }


@router.get("/me")
async def me(ctx: AuthContext = Depends(current_allow_change)) -> dict:
    return {
        "user": _user_dict(ctx.user),
        "csrf_token": ctx.record.csrf_token,
        "is_admin": ctx.user.role == "admin",
        "must_change_password": ctx.user.must_change_password,
    }


@router.post("/logout")
async def logout(
    response: Response,
    ctx: AuthContext = Depends(user_csrf_allow_change),
    services: Services = Depends(get_services),
) -> dict:
    await services.auth.logout(ctx.record)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordBody,
    ctx: AuthContext = Depends(user_csrf_allow_change),
    services: Services = Depends(get_services),
) -> dict:
    await services.auth.change_password(
        ctx.user,
        body.current_password,
        body.new_password,
        body.new_password_confirmation,
    )
    return {"ok": True}
