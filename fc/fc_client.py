"""函数计算 FC 3.0 (2023-03-30) OpenAPI Python SDK 封装。

基于官方 API 元数据 (product=FC, version=2023-03-30) 生成：
- SDK 包: alibabacloud_fc20230330
- Endpoint: <主账号ID>.<region>.fc.aliyuncs.com  (必须含账号ID)
- FC 3.0 已取消 Service 概念，函数直接在 /2023-03-30/functions 下创建
- 常见创建链路: 创建函数(CreateFunction) -> 创建触发器(CreateTrigger)

RAM 权限要求(最小):
- fc:CreateFunction
- fc:CreateTrigger
- fc:CreateAlias / fc:CreateCustomDomain (按需)

安装依赖:
    pip install alibabacloud_fc20230330
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from alibabacloud_fc20230330.client import Client as FCClient
from alibabacloud_fc20230330 import models as fc_models
from alibabacloud_tea_openapi.models import Config

logger = logging.getLogger(__name__)


class FCClientWrapper:
    """FC 3.0 客户端封装：创建函数 / 触发器 / 别名。"""

    def __init__(
        self,
        account_id: str,
        region: str,
        access_key_id: str,
        access_key_secret: str,
        security_token: Optional[str] = None,
    ) -> None:
        """初始化 FC 3.0 客户端。

        Args:
            account_id: 阿里云主账号ID（Endpoint 必须包含）
            region: 地域, 如 cn-hangzhou
            access_key_id / access_key_secret: AK/SK
            security_token: 使用 STS 临时凭证(AssumeRole)时传入
        """
        endpoint = f"{account_id}.{region}.fc.aliyuncs.com"
        cfg = Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            security_token=security_token,
            endpoint=endpoint,
        )
        self.client = FCClient(cfg)
        self.account_id = account_id
        self.region = region

    # ------------------------------------------------------------------
    # 创建函数
    # ------------------------------------------------------------------
    def create_function(
        self,
        function_name: str,
        handler: str,
        runtime: str,
        *,
        description: Optional[str] = None,
        code_zip_path: Optional[Path] = None,
        zip_file_b64: Optional[str] = None,
        oss_bucket_name: Optional[str] = None,
        oss_object_name: Optional[str] = None,
        memory_size: int = 512,
        cpu: Optional[float] = None,
        timeout: int = 60,
        disk_size: int = 512,
        internet_access: bool = True,
        environment_variables: Optional[Dict[str, str]] = None,
        role: Optional[str] = None,
        layers: Optional[list[str]] = None,
        tags: Optional[list[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """创建函数。

        code 提供方式三选一（按优先级）:
        1. code_zip_path  -> 读取本地 zip 并 base64 内联
        2. zip_file_b64   -> 直接给 base64 串
        3. oss_bucket_name + oss_object_name -> 引用 OSS 上的代码包

        runtime 取值参见 CreateFunctionInput: python3.10 / python3.12 / nodejs20
        / go1 / java11 / custom-container 等。

        函数名命名规则: 字母/数字/下划线(_)/短划线(-), 不能以数字或短划线开头,
        长度 1~64 字符。多租户场景建议前缀如 "user_{id}_fn"。
        """
        code_input: Optional[fc_models.InputCodeLocation] = None
        if code_zip_path is not None:
            zip_file_b64 = base64.b64encode(code_zip_path.read_bytes()).decode()
        if zip_file_b64 is not None:
            code_input = fc_models.InputCodeLocation(zip_file=zip_file_b64)
        elif oss_bucket_name and oss_object_name:
            code_input = fc_models.InputCodeLocation(
                oss_bucket_name=oss_bucket_name,
                oss_object_name=oss_object_name,
            )

        body = fc_models.CreateFunctionInput(
            function_name=function_name,
            handler=handler,
            runtime=runtime,
            description=description,
            code=code_input,
            memory_size=memory_size,
            cpu=cpu,
            timeout=timeout,
            disk_size=disk_size,
            internet_access=internet_access,
            environment_variables=environment_variables,
            role=role,
            layers=layers,
            tags=tags,
        )
        request = fc_models.CreateFunctionRequest(body=body)
        logger.info("creating function: %s (runtime=%s)", function_name, runtime)
        resp = self.client.create_function(request)
        return self._to_dict(resp.body)


    # ------------------------------------------------------------------
    # 创建触发器
    # ------------------------------------------------------------------
    def create_http_trigger(
        self,
        function_name: str,
        trigger_name: str,
        *,
        description: Optional[str] = None,
        methods: Optional[list[str]] = None,
        auth_type: str = "anonymous",
        disable_url_internet: bool = False,
    ) -> Dict[str, Any]:
        """为函数创建 HTTP 触发器。

        HTTPTriggerConfig 字段(JSON 字符串形式放入 trigger_config):
        - methods: ["GET","POST",...]
        - authType: "anonymous" | "function" (开启签名鉴权)
        - disableURLInternet: true=禁止公网访问(仅内网)
        """
        methods = methods or ["GET", "POST"]
        config_json = json.dumps(
            {
                "methods": methods,
                "authType": auth_type,
                "disableURLInternet": disable_url_internet,
            },
            ensure_ascii=False,
        )
        return self.create_trigger(
            function_name=function_name,
            trigger_name=trigger_name,
            trigger_type="http",
            trigger_config_json=config_json,
            description=description,
        )

    def create_timer_trigger(
        self,
        function_name: str,
        trigger_name: str,
        cron_expression: str,
        *,
        description: Optional[str] = None,
        enable: bool = True,
        payload: str = "",
    ) -> Dict[str, Any]:
        """为函数创建定时触发器。cron_expression 例: "0 0 8 * * *" (每天8点)。"""
        config_json = json.dumps(
            {
                "cronExpression": cron_expression,
                "enable": enable,
                "payload": payload,
            },
            ensure_ascii=False,
        )
        return self.create_trigger(
            function_name=function_name,
            trigger_name=trigger_name,
            trigger_type="timer",
            trigger_config_json=config_json,
            description=description,
        )

    def create_trigger(
        self,
        function_name: str,
        trigger_name: str,
        trigger_type: str,
        trigger_config_json: str,
        *,
        description: Optional[str] = None,
        invocation_role: Optional[str] = None,
        qualifier: str = "LATEST",
        source_arn: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建任意类型触发器。trigger_config_json 为对应类型的 JSON 字符串。

        triggerType: http / timer / oss / log / tablestore / mns_topic /
                     cdn_events / eventbridge
        """
        body = fc_models.CreateTriggerInput(
            trigger_name=trigger_name,
            trigger_type=trigger_type,
            trigger_config=trigger_config_json,
            description=description,
            invocation_role=invocation_role,
            qualifier=qualifier,
            source_arn=source_arn,
        )
        request = fc_models.CreateTriggerRequest(body=body)
        logger.info(
            "creating trigger: %s (type=%s) on function %s",
            trigger_name, trigger_type, function_name,
        )
        resp = self.client.create_trigger(function_name, request)
        return self._to_dict(resp.body)


    # ------------------------------------------------------------------
    # 创建函数别名 (可选, 便于版本管理)
    # ------------------------------------------------------------------
    def create_alias(
        self,
        function_name: str,
        alias_name: str,
        version_id: str = "1",
        *,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        body = fc_models.CreateAliasInput(
            alias_name=alias_name,
            version_id=version_id,
            description=description,
        )
        request = fc_models.CreateAliasRequest(body=body)
        resp = self.client.create_alias(function_name, request)
        return self._to_dict(resp.body)


    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _to_dict(obj: Any) -> Dict[str, Any]:
        """将 SDK 模型对象转为普通 dict（tea 模型的 to_map）。"""
        if obj is None:
            return {}
        try:
            return obj.to_map()
        except AttributeError:
            return json.loads(json.dumps(obj, default=str))
