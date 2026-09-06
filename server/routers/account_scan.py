"""抖音扫码登录接口（短连接 + 前端轮询）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from server.deps import AuthContext, Services, current_user, get_services, user_csrf
from server.schemas import (
    OkResponse,
    ScanQrResponse,
    ScanStartBody,
    ScanStartResponse,
    ScanStatusResponse,
    ScanVerifyCodeBody,
    ScanVerifyCodeResponse,
)
from core.services import NotFound, ValidationError
from core.services.account_scan import DouyinScanService, ScanError

router = APIRouter(prefix="/api/accounts/scan", tags=["account-scan"])


def _scan_service(sessionid: str) -> DouyinScanService:
    return DouyinScanService(sessionid)


@router.post("", response_model=ScanStartResponse)
async def start_scan(
    body: ScanStartBody,
    ctx: AuthContext = Depends(user_csrf),
) -> dict:
    try:
        sessionid = await DouyinScanService.start(body.fingerprint)
    except ScanError as error:
        if "server_busy" in str(error):
            raise HTTPException(503, "浏览器资源不足，请稍后重试") from error
        raise HTTPException(400, f"启动扫码失败: {error}") from error
    return {"sessionid": sessionid}


@router.get("/{sessionid}/qr", response_model=ScanQrResponse)
async def get_scan_qr(
    sessionid: str,
    ctx: AuthContext = Depends(current_user),
) -> dict:
    try:
        status, qr_base64 = await _scan_service(sessionid).get_qr()
    except NotFound as error:
        raise HTTPException(404, str(error)) from error
    return {"status": status, "qr_base64": qr_base64}


@router.get("/{sessionid}/status", response_model=ScanStatusResponse)
async def get_scan_status(
    sessionid: str,
    ctx: AuthContext = Depends(current_user),
    services: Services = Depends(get_services),
) -> dict:
    try:
        status, account = await _scan_service(sessionid).get_status(
            ctx.user.id, services.cookie_cipher
        )
    except NotFound as error:
        raise HTTPException(404, str(error)) from error
    except ValidationError as error:
        raise HTTPException(400, str(error)) from error
    except ScanError as error:
        raise HTTPException(400, f"扫码失败: {error}") from error
    return {"status": status, "account": account}


@router.post("/{sessionid}/refresh-qr", response_model=ScanQrResponse)
async def refresh_scan_qr(
    sessionid: str,
    ctx: AuthContext = Depends(user_csrf),
) -> dict:
    try:
        status, qr_base64 = await _scan_service(sessionid).refresh_qr()
    except NotFound as error:
        raise HTTPException(404, str(error)) from error
    return {"status": status, "qr_base64": qr_base64}


@router.post("/{sessionid}/verify-code", response_model=ScanVerifyCodeResponse)
async def verify_scan_code(
    sessionid: str,
    body: ScanVerifyCodeBody,
    ctx: AuthContext = Depends(user_csrf),
) -> dict:
    try:
        status = await _scan_service(sessionid).verify_code(body.code)
    except NotFound as error:
        raise HTTPException(404, str(error)) from error
    except ValidationError as error:
        raise HTTPException(400, str(error)) from error
    return {"status": status}


@router.post("/{sessionid}/cancel", response_model=OkResponse)
async def cancel_scan(
    sessionid: str,
    ctx: AuthContext = Depends(user_csrf),
) -> dict:
    try:
        await _scan_service(sessionid).cancel()
    except NotFound:
        # 已经不存在也算取消成功
        pass
    return {"ok": True}
