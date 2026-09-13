from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from core.services.installation import InstallationService
from server.deps import AuthContext, admin_csrf, get_settings, require_admin

router = APIRouter(prefix='/api/install', tags=['install'])


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    accessKeyId: str = Field(min_length=1, max_length=256)
    accessKeySecret: SecretStr = Field(min_length=1, max_length=256)


class DeployBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    region: str = Field(max_length=64)
    stackName: str = Field(max_length=128)
    credentials: Credentials
    parameters: dict[str, str] = Field(default_factory=dict, max_length=32)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation: str = Field(min_length=1, max_length=128)


class RepairBody(ConfirmBody):
    credentials: Credentials


@router.get('/status')
async def status(ctx: AuthContext = Depends(require_admin)) -> dict:
    return await InstallationService(get_settings()).status()


@router.post('/deploy')
async def deploy(body: DeployBody, ctx: AuthContext = Depends(admin_csrf)) -> dict:
    request = body.model_dump()
    request['credentials']['accessKeySecret'] = body.credentials.accessKeySecret.get_secret_value()
    return await InstallationService(get_settings()).deploy(request)


@router.post('/refresh')
async def refresh(ctx: AuthContext = Depends(admin_csrf)) -> dict:
    return await InstallationService(get_settings()).refresh()


@router.post('/credentials')
async def repair(body: RepairBody, ctx: AuthContext = Depends(admin_csrf)) -> dict:
    return await InstallationService(get_settings()).repair_credentials({
        'accessKeyId': body.credentials.accessKeyId,
        'accessKeySecret': body.credentials.accessKeySecret.get_secret_value(),
    }, body.confirmation)


@router.post('/cleanup')
async def cleanup(body: ConfirmBody, ctx: AuthContext = Depends(admin_csrf)) -> dict:
    return await InstallationService(get_settings()).cleanup(body.confirmation)


@router.post('/reset')
async def reset(body: ConfirmBody, ctx: AuthContext = Depends(admin_csrf)) -> dict:
    return await InstallationService(get_settings()).reset(body.confirmation)


@router.post('/discard')
async def discard(body: ConfirmBody, ctx: AuthContext = Depends(admin_csrf)) -> dict:
    """丢弃从未创建资源栈的失败请求（创建请求被确定性拒绝时记录无法清理/重置的死锁出口）。"""
    return await InstallationService(get_settings()).discard_unconfirmed(body.confirmation)
