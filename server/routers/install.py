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
