"""EventBridge 基础设施 OpenAPI 预置：事件总线 / Connection / ApiDestination / Rule。

ROS 的资源类型仅支持 ``ALIYUN::EventBridge::Rule``（2025-04 新增），不含
EventBus / Connection / ApiDestination（模板校验报 ``Unknown resource Type``），
因此这条定时调度链路改为由控制台在安装部署完成阶段以 OpenAPI 幂等创建：

    编排顺序: 事件总线 -> Connection(Bearer 鉴权) -> ApiDestination(→任务执行器
    HTTP 触发器 URL) -> Rule(定时事件源产物 events 路由到 API 端点)。

所有 ensure_* 均为幂等：资源已存在时跳过（ApiDestination 额外做指向校对）。
"""

from __future__ import annotations

import logging

from alibabacloud_eventbridge20200401 import models as eb
from alibabacloud_eventbridge20200401.client import Client as EbClient
from alibabacloud_tea_openapi.models import Config

logger = logging.getLogger(__name__)

_EXISTS_CODES = {
    "EventBusAlreadyExists", "EventBusAlreadyExist",
    "ConnectionAlreadyExists", "ConnectionAlreadyExist",
    "ApiDestinationAlreadyExists", "ApiDestinationAlreadyExist",
    "RuleAlreadyExists", "RuleAlreadyExist", "RuleAlreadyExistException",
    "ResourceAlreadyExists", "AlreadyExists", "ObjectDuplicate",
}


def _client(region: str, ak: str, sk: str) -> EbClient:
    from alibabacloud_tea_openapi.models import Config as Cfg
    return EbClient(Cfg(
        access_key_id=ak, access_key_secret=sk,
        endpoint=f"eventbridge.{region}.aliyuncs.com",
        connect_timeout=10000, read_timeout=30000,
    ))


def _account_id(region: str, ak: str, sk: str) -> str:
    """经 STS GetCallerIdentity 解析主账号 ID（规则投递目标 ARN 需要）。"""
    from alibabacloud_sts20150401.client import Client as StsClient
    sts = StsClient(Config(
        access_key_id=ak, access_key_secret=sk,
        endpoint="sts.aliyuncs.com", connect_timeout=10000, read_timeout=30000,
    ))
    resp = sts.get_caller_identity()
    account = getattr(resp.body, "account_id", "") or ""
    if not account:
        raise RuntimeError("STS GetCallerIdentity 未返回账号 ID")
    return account


def ensure_event_bus(region: str, ak: str, sk: str, name: str,
                     description: str = "continuation browser scheduled-task event bus") -> None:
    try:
        _client(region, ak, sk).create_event_bus(eb.CreateEventBusRequest(
            event_bus_name=name, description=description,
        ))
        logger.info("event bridge bus created: %s", name)
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "code", "") not in _EXISTS_CODES:
            raise


def ensure_connection(region: str, ak: str, sk: str, name: str, bearer: str,
                      description: str = "call continuation task executor HTTP trigger (Bearer auth)") -> None:
    try:
        _client(region, ak, sk).create_connection(eb.CreateConnectionRequest(
            connection_name=name,
            description=description,
            network_parameters=eb.CreateConnectionRequestNetworkParameters(network_type="PublicNetwork"),
            auth_parameters=eb.CreateConnectionRequestAuthParameters(
                authorization_type="API_KEY_AUTH",
                api_key_auth_parameters=eb.CreateConnectionRequestAuthParametersApiKeyAuthParameters(
                    api_key_name="Authorization", api_key_value=f"Bearer {bearer}",
                ),
            ),
        ))
        logger.info("event bridge connection created: %s", name)
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "code", "") not in _EXISTS_CODES:
            raise


def ensure_api_destination(region: str, ak: str, sk: str, name: str, connection_name: str,
                           endpoint: str, description: str = "API endpoint to continuation task HTTP trigger") -> None:
    client = _client(region, ak, sk)
    try:
        client.create_api_destination(eb.CreateApiDestinationRequest(
            api_destination_name=name, connection_name=connection_name, description=description,
            http_api_parameters=eb.CreateApiDestinationRequestHttpApiParameters(endpoint=endpoint, method="POST"),
        ))
        logger.info("event bridge api destination created: %s", name)
        return
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "code", "") not in _EXISTS_CODES:
            raise
    # 已存在：校对投递端点，避免旧端点残留导致规则打到错误地址。
    try:
        client.update_api_destination(eb.UpdateApiDestinationRequest(
            api_destination_name=name, connection_name=connection_name, description=description,
            http_api_parameters=eb.UpdateApiDestinationRequestHttpApiParameters(endpoint=endpoint, method="POST"),
        ))
        logger.info("event bridge api destination reconciled: %s", name)
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "code", "") not in _EXISTS_CODES:
            raise


def ensure_rule(region: str, ak: str, sk: str, bus_name: str, rule_name: str,
                api_destination_name: str, description: str = "schedule events -> api destination") -> None:
    targets = [eb.CreateRuleRequestEventTargets(
        id="taskrunner-api-destination",
        type="acs.api.destination",
        endpoint=f"acs:api-destination:{region}:{_account_id(region, ak, sk)}:name/{api_destination_name}",
        push_retry_strategy="BACKOFF_RETRY",
        errors_tolerance="NONE",
        param_list=[
            eb.CreateRuleRequestEventTargetsParamList(
                resource_key="Name", form="CONSTANT", value=api_destination_name,
            ),
            eb.CreateRuleRequestEventTargetsParamList(
                resource_key="HeaderParameters", form="TEMPLATE", value='{"headerKey1":"Content-Type","headerValue1":"application/json"}',
                template='{"${headerKey1}":"${headerValue1}"}',
            ),
            eb.CreateRuleRequestEventTargetsParamList(resource_key="BodyParameters", form="ORIGINAL", value=""),
        ],
    )]
    try:
        _client(region, ak, sk).create_rule(eb.CreateRuleRequest(
            event_bus_name=bus_name, rule_name=rule_name, description=description,
            filter_pattern="{}", status="ENABLE", event_targets=targets,
        ))
        logger.info("event bridge rule created: %s/%s", bus_name, rule_name)
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "code", "") not in _EXISTS_CODES:
            raise


def ensure_infrastructure(region: str, ak: str, sk: str, *, bus_name: str, connection_name: str,
                          api_destination_name: str, rule_name: str, task_trigger_url: str,
                          bearer: str) -> None:
    """幂等预置 EventBridge 全套基础设施（顺序依赖）。"""
    ensure_event_bus(region, ak, sk, bus_name)
    ensure_connection(region, ak, sk, connection_name, bearer)
    ensure_api_destination(region, ak, sk, api_destination_name, connection_name, task_trigger_url)
    ensure_rule(region, ak, sk, bus_name, rule_name, api_destination_name)