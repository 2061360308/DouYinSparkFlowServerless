"""示例：为租户/用户在其账号中创建云函数（FC 3.0, 2023-03-30）。

两种典型部署模式：
1. 单账号模式（函数建在你的主账号下，按命名隔离用户）
   平台持有一个 RAM 用户 AK，为每个终端用户创建独立命名的函数。
2. 跨账号模式（函数建在终端用户自己的账号下）
   用户在其账号创建 RAM 角色并信任你的账号(AssumeRole)，你换取 STS
   临时凭证后用同一套 FC Client 创建，资源归属用户账号、在用户控制台可见。

本示例演示模式2（AssumeRole -> 为用户创建函数），模式1只需把凭证换成
平台自己的 AK 即可（security_token 置空）。

安装依赖:
    pip install alibabacloud_fc20230330 alibabacloud_sts20150401
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from alibabacloud_fc20230330.client import Client as FCClient
from alibabacloud_fc20230330 import models as fc_models
from alibabacloud_sts20150401.client import Client as StsClient
from alibabacloud_sts20150401 import models as sts_models
from alibabacloud_tea_openapi.models import Config as TeaConfig

# ---------------- 平台方自身 AK（用于换取用户账号的 STS 凭证） ----------------
PLATFORM_ACCESS_KEY_ID = "LTAI5t********"      # 平台 RAM 用户 AK
PLATFORM_ACCESS_KEY_SECRET = "your_secret"      # 平台 RAM 用户 SK
REGION = "cn-hangzhou"


def assume_user_role(role_arn: str, session_name: str) -> Dict[str, str]:
    """用平台身份 AssumeRole 到用户的 RAM 角色，换取 STS 临时凭证。

    role_arn 形如: acs:ram::<用户主账号ID>:role/<用户创建的角色名>
    该角色必须: 可信实体=平台账号, 且被授予 AliyunFCFullAccess(或 fc:*)
    """
    sts_client = StsClient(
        TeaConfig(
            access_key_id=PLATFORM_ACCESS_KEY_ID,
            access_key_secret=PLATFORM_ACCESS_KEY_SECRET,
            endpoint=f"sts.aliyuncs.com",
        )
    )
    resp = sts_client.assume_role(
        sts_models.AssumeRoleRequest(
            role_arn=role_arn,
            role_session_name=session_name,
            duration_seconds=3600,
        )
    )
    creds = resp.body.credentials
    return {
        "access_key_id": creds.access_key_id,
        "access_key_secret": creds.access_key_secret,
        "security_token": creds.security_token,
    }


def build_fc_client(account_id: str, creds: Dict[str, str]) -> FCClient:
    """按 FC 3.0 规范构造 Client：endpoint 必须带账号ID。

    注意: FC 3.0 (2023-03-30) 中 CreateFunction/CreateTrigger 都直接通过
    client 方法调用，request body 为对应 Input 模型；无需也不存在
    CreateService 一步（3.0 已取消 Service 概念）。
    """
    config = TeaConfig(
        access_key_id=creds["access_key_id"],
        access_key_secret=creds["access_key_secret"],
        security_token=creds.get("security_token"),
        endpoint=f"{account_id}.{REGION}.fc.aliyuncs.com",
    )
    return FCClient(config)


def create_function_for_user(
    fc_client: FCClient,
    user_id: str,
    *,
    runtime: str = "python3.10",
    handler: str = "index.handler",
    code_oss_bucket: Optional[str] = None,
    code_oss_object: Optional[str] = None,
    env_vars: Optional[Dict[str, str]] = None,
    description: str = "created by platform for tenant",
) -> Dict[str, Any]:
    """为用户创建云函数。

    函数名以用户维度隔离: fn_{user_id}（满足 1~64 位、字母数字_-
    命名规则；FC 3.0 无服务概念，函数为顶层资源，天然不冲突）。
    """
    function_name = f"fn_{user_id}"
    # code 二选一: OSS 引用 或 base64 内联（见 fc/fc_client.py）
    code = fc_models.InputCodeLocation(
        oss_bucket_name=code_oss_bucket,
        oss_object_name=code_oss_object,
    ) if (code_oss_bucket and code_oss_object) else None

    req = fc_models.CreateFunctionRequest(
        body=fc_models.CreateFunctionInput(
            function_name=function_name,
            runtime=runtime,
            handler=handler,
            description=description,
            code=code,
            memory_size=512,
            timeout=60,
            environment_variables=env_vars,
            # 函数执行角色（可选，函数内需访问 OSS 等时使用）
            # role="acs:ram::<用户账号>:role/<执行角色>",
        )
    )
    resp = fc_client.create_function(req)
    return json.loads(json.dumps(resp.body.to_map(), default=str))


def create_http_trigger_for_user(
    fc_client: FCClient,
    function_name: str,
) -> Dict[str, Any]:
    """为用户函数创建 HTTP 触发器并返回访问地址。"""
    trigger_config = json.dumps(
        {"methods": ["GET", "POST"], "authType": "anonymous", "disableURLInternet": False},
        ensure_ascii=False,
    )
    req = fc_models.CreateTriggerRequest(
        body=fc_models.CreateTriggerInput(
            trigger_name="default-http",
            trigger_type="http",
            trigger_config=trigger_config,
            qualifier="LATEST",
            description="public http trigger",
        )
    )
    resp = fc_client.create_trigger(function_name, req)
    return json.loads(json.dumps(resp.body.to_map(), default=str))


if __name__ == "__main__":
    # 用户主账号ID（角色所在账号，也是函数归属账号）
    USER_ACCOUNT_ID = "188077086902****"
    # 用户在控制台为该角色配置的 RAM 角色 ARN
    USER_ROLE_ARN = "acs:ram::188077086902****:role/fc-provision-role"

    # 1) 平台 AssumeRole 到用户账号
    sts = assume_user_role(USER_ROLE_ARN, session_name="plat-provision")
    # 2) 构造 FC 3.0 client（归属=用户账号）
    fc = build_fc_client(account_id=USER_ACCOUNT_ID, creds=sts)
    # 3) 为用户建函数 + HTTP 触发器
    fn = create_function_for_user(fc, user_id="u_10001")
    print("function created:", fn)
    trig = create_http_trigger_for_user(fc, function_name=fn["functionName"])
    print("trigger created:", trig)
    print("public url:", trig.get("httpTrigger", {}).get("urlInternet"))
