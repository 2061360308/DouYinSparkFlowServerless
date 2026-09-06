"""Admin installation orchestration. No background jobs or process-local truth.

The database owns request identity; ROS owns resource status. Repeated submissions
reuse the same client token, including when the first response was lost.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tortoise.transactions import in_transaction
import yaml

from aliyunFC.install import RosStackClient
from core.browser.manager import is_docker_deployment
from core.config import Settings
from core.db.connection import with_db
from core.db.models.installation import Installation
from core.db.system_config_db import SystemConfigDB
from core.services import Conflict, NotFound, ValidationError

TEMPLATE = Path(__file__).resolve().parents[2] / 'aliyunFC/install/ros-template.yaml'
AAD = b'douyinspark-installation-v1'
SPEC_KEYS = {'Cpu', 'MemorySize', 'DiskSize', 'FunctionTimeout', 'TaskCpu', 'TaskMemorySize', 'TaskFunctionTimeout'}
FIXED_KEYS = {
    'NamePrefix', 'FunctionName', 'ImageUrl', 'ContainerPort', 'TriggerName', 'TriggerAuthType',
    'TaskFunctionName', 'TaskImageUrl', 'TaskContainerPort', 'TaskTriggerName',
    'EventBusName', 'ApiDestinationName', 'ConnectionName', 'RuleName',
}
OUTPUT_CONFIG = {
    'TriggerUrlInternet': 'fc_function_url', 'FunctionName': 'function_name',
    'TaskTriggerUrlInternet': 'task_function_url', 'TaskFunctionName': 'task_function_name',
    'EventBusName': 'eventbridge_bus_name',
}


def _https_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return parts.scheme == 'https' and bool(parts.hostname) and not parts.username and not parts.password
    except ValueError:
        return False


def _validated_parameters(values: dict[str, str]) -> dict[str, str]:
    schema = yaml.safe_load(TEMPLATE.read_text(encoding='utf-8'))['Parameters']
    if values.keys() - (SPEC_KEYS | FIXED_KEYS):
        raise ValidationError('包含未支持的部署参数')
    for key in FIXED_KEYS & values.keys():
        if values[key] != str(schema[key]['Default']):
            raise ValidationError(f'{key} 必须使用服务器模板默认值')
    result = {key: str(schema[key]['Default']) for key in SPEC_KEYS | FIXED_KEYS}
    result.update(values)
    try:
        for prefix, floor in (('', 1536), ('Task', 128)):
            cpu = float(result[prefix + 'Cpu'])
            memory = float(result[prefix + 'MemorySize'])
            timeout = float(result[prefix + 'FunctionTimeout'])
            if not all(math.isfinite(v) for v in (cpu, memory, timeout)):
                raise ValueError()
            if not 0.05 <= cpu <= 16 or not math.isclose(cpu / 0.05, round(cpu / 0.05), abs_tol=1e-8):
                raise ValueError()
            if memory % 64 or not max(floor, cpu * 1024) <= memory <= cpu * 4096:
                raise ValueError()
            if not timeout.is_integer() or not 1 <= timeout <= 86400:
                raise ValueError()
        if result['DiskSize'] not in ('512', '10240'):
            raise ValueError()
    except (ValueError, OverflowError):
        raise ValidationError('函数规格不合法，请检查 CPU、内存、磁盘和超时') from None
    return result


def _payload(row: Installation, settings: Settings) -> dict:
    try:
        raw = AESGCM(settings.cookie_key).decrypt(row.nonce, row.ciphertext, AAD)
        return json.loads(raw)
    except Exception:
        raise ValidationError('无法解密安装凭据，请确认部署时的 SPARK_COOKIE_KEY_B64 未变更') from None


def _client(payload: dict):
    return RosStackClient(region=payload['region'], access_key_id=payload['credentials']['accessKeyId'],
                          access_key_secret=payload['credentials']['accessKeySecret'])


def _view(row: Installation) -> dict:
    state = row.status
    if state == 'SUBMITTING' or state.endswith('_IN_PROGRESS') or state == 'REVIEW_IN_PROGRESS':
        state = 'CREATE_IN_PROGRESS'
    elif state != 'CREATE_COMPLETE':
        state = 'CREATE_FAILED'
    return {'stackId': row.stack_id, 'status': state, 'rawStatus': row.status,
            'statusReason': row.status_reason or ('' if state != 'CREATE_FAILED' else '资源栈部署失败或已回滚，请在 ROS 控制台检查原因并处理资源栈。'),
            'events': [], 'outputs': row.outputs or None}


class InstallationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def prerequisites(self) -> list[str]:
        missing = []
        if not _https_url(self.settings.public_base_url):
            missing.append('SPARK_PUBLIC_BASE_URL（公开 HTTPS 地址）')
        if len(self.settings.service_token) < 32:
            missing.append('SPARK_SERVICE_TOKEN（至少 32 字符）')
        if self.settings.dev_insecure:
            missing.append('关闭 SPARK_DEV_INSECURE，配置固定加密密钥')
        return missing

    @with_db
    async def status(self) -> dict:
        row = await Installation.get_or_none(id=1)
        config = await SystemConfigDB.get_many(list(OUTPUT_CONFIG.values()))
        legacy = await SystemConfigDB.get_many(['platform_access_key_id', 'platform_access_key_secret'])
        local = is_docker_deployment()
        installed = local or bool(all(config.values()) and (
            (row and row.status == 'CREATE_COMPLETE') or (not row and all(legacy.values()))
        ))
        return {'mode': 'local' if local else 'cloud', 'installed': installed,
                'needsInstall': not installed, 'canDeploy': not local and not self.prerequisites(),
                'missingEnv': self.prerequisites(), 'deployment': _view(row) if row else None}

    @with_db
    async def deploy(self, request: dict) -> dict:
        if is_docker_deployment():
            raise Conflict('本地浏览器模式无需创建云资源')
        if self.prerequisites():
            raise ValidationError('部署前需要配置：' + '、'.join(self.prerequisites()))
        if request['region'] != 'cn-hangzhou' or request['stackName'] != 'DouyinSpark':
            raise ValidationError('当前模板仅支持 cn-hangzhou / DouyinSpark')
        params = _validated_parameters(request['parameters'])
        credentials = request['credentials']
        if not credentials.get('accessKeyId', '').strip() or not credentials.get('accessKeySecret', '').strip():
            raise ValidationError('请输入完整的云访问凭据')
        payload = {**request, 'parameters': params}
        encoded = json.dumps(payload, sort_keys=True).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()
        params.update(ApiBaseUrl=self.settings.public_base_url, ServiceToken=self.settings.service_token,
                      BearerToken=secrets.token_urlsafe(32))
        # Persist the exact template and generated tokens before contacting ROS.
        payload['template'] = TEMPLATE.read_text(encoding='utf-8')
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.settings.cookie_key).encrypt(nonce, json.dumps(payload).encode(), AAD)
        row, _ = await Installation.get_or_create(id=1, defaults={
            'request_hash': fingerprint, 'client_token': secrets.token_hex(16),
            'nonce': nonce, 'ciphertext': ciphertext,
        })
        if row.request_hash != fingerprint:
            raise Conflict('已有安装记录，请恢复查询原部署；更换配置前需人工确认旧资源状态')
        if not row.stack_id:
            await self._submit(row)
            row = await Installation.get(id=1)
        return _view(row)

    async def _submit(self, row: Installation) -> None:
        payload = _payload(row, self.settings)
        try:
            stack_id = await asyncio.to_thread(
                _client(payload).create_stack, template_body=payload['template'],
                stack_name=payload['stackName'], parameters=payload['parameters'], client_token=row.client_token,
            )
        except Exception:
            # Do not expose SDK request/credential details. Keep the token for recovery.
            raise ValidationError('创建请求未确认成功，请恢复查询或重试同一部署；不会生成新的请求令牌') from None
        if not stack_id:
            raise ValidationError('ROS 未返回资源栈 ID，请恢复查询')
        await Installation.filter(id=1, stack_id='').update(stack_id=stack_id, status='CREATE_IN_PROGRESS')

    @with_db
    async def refresh(self) -> dict:
        row = await Installation.get_or_none(id=1)
        if row is None:
            raise NotFound('尚未提交部署')
        if not row.stack_id:
            await self._submit(row)
            row = await Installation.get(id=1)
        payload = _payload(row, self.settings)
        if row.status == 'CREATE_COMPLETE':
            info = {'Status': 'CREATE_COMPLETE', 'Outputs': [
                {'OutputKey': k, 'OutputValue': v} for k, v in row.outputs.items()
            ]}
        else:
            try:
                info = await asyncio.to_thread(_client(payload).get_stack_status, row.stack_id)
            except Exception:
                raise ValidationError('暂时无法查询 ROS 状态，请稍后重试') from None
        state = info.get('Status', 'UNKNOWN')
        outputs = {item['OutputKey']: item.get('OutputValue', '') for item in info.get('Outputs', []) if 'OutputKey' in item}
        # Both config and completion commit together. A delayed query cannot undo completion.
        async with in_transaction():
            current = await Installation.filter(id=1).select_for_update().get()
            if current.status == 'CREATE_COMPLETE':
                state, outputs = 'CREATE_COMPLETE', current.outputs
            if state == 'CREATE_COMPLETE':
                if not all(isinstance(outputs.get(key), str) and outputs[key] for key in OUTPUT_CONFIG):
                    raise ValidationError('资源栈已完成但关键输出缺失，尚未保存安装结果')
                if not _https_url(outputs['TriggerUrlInternet']) or not _https_url(outputs['TaskTriggerUrlInternet']):
                    raise ValidationError('资源栈输出的函数地址不合法')
                values = {target: outputs[key] for key, target in OUTPUT_CONFIG.items()}
                values['region'] = payload['region']
                await SystemConfigDB.set_many(values)
                current.outputs = {key: value for key, value in outputs.items() if key in OUTPUT_CONFIG}
            current.status = state
            reason = str(info.get('StatusReason', ''))
            for secret in (*payload['credentials'].values(), payload['parameters']['ServiceToken'], payload['parameters']['BearerToken']):
                if secret:
                    reason = reason.replace(secret, '[redacted]')
            current.status_reason = '' if state == 'CREATE_COMPLETE' else reason[:1000]
            await current.save(update_fields=['status', 'status_reason', 'outputs'])
        return _view(current)


@with_db
async def installed_credentials(settings: Settings | None = None) -> dict[str, str]:
    """Server-only credential access; never part of the admin config response."""
    row = await Installation.get_or_none(id=1, status='CREATE_COMPLETE')
    if not row:
        return {}
    payload = _payload(row, settings or Settings.from_env())
    return {'platform_access_key_id': payload['credentials']['accessKeyId'],
            'platform_access_key_secret': payload['credentials']['accessKeySecret']}
