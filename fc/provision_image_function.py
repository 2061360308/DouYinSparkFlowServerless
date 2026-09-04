"""FC 容器镜像函数自动部署：分步向导式函数库 + 一键编排。

设计定位
--------
供 Web 面板按向导逐步调用（每步独立、自包含，失败互不影响），也可一次
编排完整流程。三个向导步骤对应三个公共函数：

    第 1 步 账号与角色校验   validate_account(cfg)
        - 平台 AK AssumeRole -> 目标账号 STS（验证角色可达、账号归属一致）
        - 自动确保 FC 服务关联角色 AliyunServiceRoleForFC 就绪（挂 VPC 必需）
    第 2 步 VPC 网络链路      ensure_network(cfg, existing=None)
        - VPC -> 交换机 -> 安全组 -> 增强型按量 NAT(按CU) -> EIP(按流量)
          -> 绑定 NAT -> SNAT（函数出公网即固定为该 EIP）
    第 3 步 函数与触发器      deploy_function(cfg, net)
        - runtime=custom-container + vpcConfig + internetAccess=false
        - Header 会话亲和（HEADER_FIELD） + 签名 HTTP 触发器

    一键编排                    provision_all(cfg)      # 1->2->3 串联

配置来源
--------
不再读取环境变量。配置键已全部注册进 db.SYSTEM_CONFIG_KEYS（键与默认值见
下方 CONFIG_FIELDS，为唯一权威默认值来源），由 Web 面板引导用户填写后通过
``SystemConfigDB.set_many()`` 落库；本模块提供：

    async load_config_from_db() -> cfg     # 从 db 读全部键并规范化
    async save_config_to_db(cfg)           # 将 cfg 写回 db（供面板保存草稿）

读取键 / 类型转换 / 步骤分组与默认值均由 CONFIG_FIELDS 一份元数据驱动，
新增配置项只需在 CONFIG_FIELDS 追加一行，并在 db/models.py 的
SYSTEM_CONFIG_KEYS 同步注册同名键与默认值。

错误处理
--------
所有失败以 ProvisionError 抛出（message 为可直接展示给用户的中文说明，
created 携带已完成步骤的资源清单）；面板侧捕获后展示即可，脚本绝不
sys.exit、绝不读环境变量。资源中途失败不自动回滚（避免误删既有资源）。

Web 后端集成建议：
    from fc.provision_image_function import validate_account, ...
    # 同步 SDK 调用建议放入线程池避免阻塞事件循环:
    result = await asyncio.to_thread(validate_account, cfg)

部署前提（目标账号内被扮演角色的 RAM 权限，建议自定义最小策略）:
  VPC链路 : vpc:CreateVpc / vpc:DescribeVpcs / vpc:CreateVSwitch
            vpc:DescribeVSwitches / vpc:DescribeZones
  NAT/EIP : vpc:CreateNatGateway / vpc:DescribeNatGateways
            vpc:AllocateEipAddress / vpc:DescribeEipAddresses
            vpc:AssociateEipAddress / vpc:CreateSnatEntry
  安全组  : ecs:CreateSecurityGroup
  服务关联角色: ram:GetRole / ram:CreateServiceLinkedRole（auto_create_slr=true 时）
  函数    : fc:GetFunction / fc:CreateFunction / fc:CreateTrigger
  平台AK需: sts:AssumeRole / sts:GetCallerIdentity
  快捷方式: AliyunVPCFullAccess + AliyunEIPFullAccess +
            AliyunECSFullAccess + AliyunFCFullAccess + AliyunRAMFullAccess

产品开通与函数执行角色（无需用户手动操作）:
  1) FC 产品本身: 阿里云自 2024-08-27 起对函数计算自动开通, 账号无需任何
     「开通服务」操作即可直接调用 API。
  2) 函数挂 VPC / 拉镜像所需的服务关联角色 AliyunServiceRoleForFC:
     第 1 步自动检查, 缺失且 auto_create_slr=true 时自动调用 RAM
     CreateServiceLinkedRole(ServiceName=fc.aliyuncs.com) 创建（幂等）。
  3) function_exec_role_arn 留空 = 不配置自定义函数执行角色, 由上述服务
     关联角色自动完成 VPC 接入；仅当函数代码还需访问目标账号内其他云资源
     (OSS/RDS 等) 时, 才填信任 fc.aliyuncs.com 的角色 ARN。

费用提示（按量、无长期占用）:
  - NAT 网关: 按CU用量计费(PayByLcu), 流量小成本极低
  - EIP    : 按流量计费(约¥0.8/GB), 绑定到NAT后不收闲置配置费
  - VPC/交换机/安全组/SNAT: 免费
  - FC     : 按实例运行时长计费; 会话亲和会保持实例存活, 请留意成本

镜像来源说明:
  官方明确支持的镜像源为同地域 ACR；Docker Hub 属"网络可达即可尝试"：
  函数置于 VPC 内通过 NAT/EIP 出公网具备拉取出口。若平台侧拉取仍失败,
  兜底: 本地 docker pull 后推送同地域 ACR, 改 image_url 即可, 其余不变。

命令行用法（从 db 读取已保存配置一键跑全流程，供调试/运维；脚本会先
自动 init_db 建表并写入默认配置）:
    python fc/provision_image_function.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from typing import Any, Dict, List, NamedTuple, Optional

from alibabacloud_ecs20140526.client import Client as EcsClient
from alibabacloud_ecs20140526 import models as ecs_models
from alibabacloud_fc20230330.client import Client as FCClient
from alibabacloud_fc20230330 import models as fc_models
from alibabacloud_ram20150501.client import Client as RamClient
from alibabacloud_ram20150501 import models as ram_models
from alibabacloud_sts20150401.client import Client as StsClient
from alibabacloud_sts20150401 import models as sts_models
from alibabacloud_tea_openapi.models import Config as TeaConfig
from alibabacloud_vpc20160428.client import Client as VpcClient
from alibabacloud_vpc20160428 import models as vpc_models

# ═══════════════════════════════════════════════════════════════════════════
# 配置字段元数据（唯一权威默认值来源；db.SYSTEM_CONFIG_KEYS 与此保持一致）
# ═══════════════════════════════════════════════════════════════════════════

# 向导步骤常量（供面板分步渲染）
STEP_ACCOUNT = "account"    # 第 1 步：账号/角色/地域 + 校验
STEP_NETWORK = "network"    # 第 2 步：VPC 网络链路
STEP_FUNCTION = "function"  # 第 3 步：函数/镜像/规格/亲和/触发器

_STEP_LABELS = {
    STEP_ACCOUNT: "账号与角色校验",
    STEP_NETWORK: "VPC 网络链路",
    STEP_FUNCTION: "函数与触发器",
}


class ConfigField(NamedTuple):
    """配置项元数据：key 与 db.SYSTEM_CONFIG_KEYS 键名一致。

    ftype: str/int/float/bool/list；step: 属于哪个向导步骤；
    required: 该步骤提交前必须填写；default 与 db 默认值保持一致。
    """

    key: str
    label: str
    ftype: str
    default: Any
    step: str
    required: bool = False
    help: str = ""


CONFIG_FIELDS: List[ConfigField] = [
    # ── 第 1 步：账号与角色 ─────────────────────────────────────────────
    ConfigField("platform_access_key_id", "平台 AK", "str", "",
                STEP_ACCOUNT, True,
                "平台侧 RAM 用户 AccessKey ID（拥有 sts:AssumeRole 权限）"),
    ConfigField("platform_access_key_secret", "平台 SK", "str", "",
                STEP_ACCOUNT, True,
                "平台侧 RAM 用户 AccessKey Secret（敏感值，建议妥善保管）"),
    ConfigField("target_account_id", "目标账号主账号 ID", "str", "",
                STEP_ACCOUNT, True,
                "资源归属账号 ID，将校验 AssumeRole 后身份确实属于该账号"),
    ConfigField("assume_role_arn", "被扮演角色 ARN", "str", "",
                STEP_ACCOUNT, True,
                "目标账号内、信任平台账号的角色 ARN，形如 acs:ram::<账号ID>:role/xxx"),
    ConfigField("role_session_name", "AssumeRole 会话名", "str", "plat-provision",
                STEP_ACCOUNT, False, "STS 会话名，默认即可"),
    ConfigField("region", "地域", "str", "cn-hangzhou",
                STEP_ACCOUNT, False, "FC 部署地域，如 cn-hangzhou"),
    ConfigField("function_exec_role_arn", "函数执行角色 ARN", "str", "",
                STEP_ACCOUNT, False,
                "可选。留空 = FC 自动使用服务关联角色接入 VPC；"
                "函数需访问目标账号内 OSS/RDS 等资源时才填写"),
    ConfigField("auto_create_slr", "自动创建 FC 服务关联角色", "bool", True,
                STEP_ACCOUNT, False,
                "FC 挂 VPC 所需角色缺失时是否自动创建（建议保持开启）"),
    # ── 第 2 步：VPC 网络链路 ────────────────────────────────────────────
    ConfigField("vpc_cidr", "VPC 网段", "str", "172.16.0.0/16",
                STEP_NETWORK, False, "VPC CIDR，默认 172.16.0.0/16"),
    ConfigField("vswitch_cidr", "交换机网段", "str", "172.16.0.0/20",
                STEP_NETWORK, False, "须为 VPC 网段的子集"),
    ConfigField("zone_id", "可用区", "str", "",
                STEP_NETWORK, False,
                "留空自动选择；若函数创建报可用区不支持，请在此填 cn-hangzhou-h 等"),
    ConfigField("eip_bandwidth_mbps", "EIP 带宽峰值(Mbps)", "str", "5",
                STEP_NETWORK, False, "按流量计费模式下的带宽上限"),
    # ── 第 3 步：函数 / 镜像 / 触发器 ────────────────────────────────────
    ConfigField("function_name", "函数名", "str", "",
                STEP_FUNCTION, True,
                "字母开头、1~64 位，仅含字母/数字/_/-；同名已存在将报错"),
    ConfigField("image_url", "容器镜像地址", "str", "",
                STEP_FUNCTION, True,
                "完整镜像地址，如 docker.io/ns/browser:v1（推荐推送到同地域 ACR）"),
    ConfigField("image_registry_username", "镜像仓库用户名", "str", "",
                STEP_FUNCTION, False, "私有仓库凭据；公开镜像留空"),
    ConfigField("image_registry_password", "镜像仓库密码", "str", "",
                STEP_FUNCTION, False, "私有仓库凭据；公开镜像留空"),
    ConfigField("container_port", "镜像监听端口", "int", 9000,
                STEP_FUNCTION, False, "镜像内 HTTP Server 监听端口（CA 端口）"),
    ConfigField("cpu_vcores", "CPU 核数", "float", 1.0,
                STEP_FUNCTION, False, ""),
    ConfigField("memory_size_mb", "内存(MB)", "int", 1536,
                STEP_FUNCTION, False, "64 的倍数，与 CPU 比例须在 1:1~1:4"),
    ConfigField("timeout_seconds", "函数超时(s)", "int", 60,
                STEP_FUNCTION, False, "1~86400"),
    ConfigField("disk_size_mb", "磁盘(MB)", "int", 512,
                STEP_FUNCTION, False, "512 或 10240"),
    ConfigField("affinity_header_field_name", "会话亲和 Header 键名", "str", "sessionid",
                STEP_FUNCTION, False, "请求携带该 Header 即命中同一实例会话"),
    ConfigField("session_concurrency_per_instance", "单实例并发 Session 数", "int", 1,
                STEP_FUNCTION, False, "1~200"),
    ConfigField("session_ttl_seconds", "Session 生命周期(s)", "int", 600,
                STEP_FUNCTION, False, ""),
    ConfigField("session_idle_timeout_seconds", "Session 空闲超时(s)", "int", 30,
                STEP_FUNCTION, False, ""),
    ConfigField("disable_session_id_reuse", "禁用 SessionID 复用", "bool", False,
                STEP_FUNCTION, False, "默认 false"),
    ConfigField("trigger_name", "HTTP 触发器名", "str", "default-http",
                STEP_FUNCTION, False, "每个函数内唯一"),
    ConfigField("trigger_methods", "HTTP 方法", "list", ["GET", "POST"],
                STEP_FUNCTION, False, "JSON 数组，如 [\"GET\", \"POST\"]"),
]

CONFIG_KEYS: List[str] = [f.key for f in CONFIG_FIELDS]
STEPS: List[str] = [STEP_ACCOUNT, STEP_NETWORK, STEP_FUNCTION]  # 向导步骤顺序
CONFIG_BY_STEP: Dict[str, List[ConfigField]] = {
    STEP_ACCOUNT: [f for f in CONFIG_FIELDS if f.step == STEP_ACCOUNT],
    STEP_NETWORK: [f for f in CONFIG_FIELDS if f.step == STEP_NETWORK],
    STEP_FUNCTION: [f for f in CONFIG_FIELDS if f.step == STEP_FUNCTION],
}


def step_label(step: str) -> str:
    return _STEP_LABELS.get(step, step)


# ═══════════════════════════════════════════════════════════════════════════
# 异常与配置规范化
# ═══════════════════════════════════════════════════════════════════════════
class ProvisionError(Exception):
    """部署失败（message 为可直接展示给用户的中文说明）。

    Attributes:
        created: 本次流程中已创建的资源清单 {key: value}（失败不自动回滚）。
    """

    def __init__(self, message: str, created: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.created = created or {}


def _coerce(ftype: str, raw: Any, label: str) -> Any:
    """按字段类型转换原始值（来自 db 字符串 / 表单 / 默认值）。"""
    # 已是目标 Python 类型（如 CONFIG_FIELDS 里的 typed 默认值）则直接采用，
    # 避免 list/bool 等被 str() 后再解析的往返问题。
    if ftype == "list" and isinstance(raw, list):
        return list(raw)
    if ftype == "bool" and isinstance(raw, bool):
        return raw
    if ftype == "int" and isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if ftype == "float" and isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if ftype == "str":
        return str(raw)
    text = str(raw).strip()
    try:
        if ftype == "int":
            return int(text)
        if ftype == "float":
            return float(text)
        if ftype == "bool":
            return text.lower() in ("1", "true", "yes", "on")
        if ftype == "list":
            try:
                val = json.loads(text)
            except (TypeError, ValueError):
                val = [x.strip() for x in text.split(",") if x.strip()]
            if isinstance(val, list):
                return val
            raise ValueError("不是 JSON 数组")
    except (TypeError, ValueError) as ex:
        raise ProvisionError(f"配置项「{label}」取值非法（期望 {ftype}），收到: {raw!r}") from ex
    raise ProvisionError(f"未知字段类型 {ftype!r}（{label}）")


def build_config(values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把面板/DB 传入的原始值（可能缺失/未填）规范化为完整 cfg。

    - 仅按 CONFIG_FIELDS 提取字段，忽略未知键；
    - 未提供或空串一律回落到该字段默认值；
    - 不做环境变量读取；缺失的必填项通过 required_missing() 检出。
    """
    raw = dict(values or {})
    cfg: Dict[str, Any] = {}
    for f in CONFIG_FIELDS:
        v = raw.get(f.key)
        if v is None or v == "":
            v = f.default
        cfg[f.key] = _coerce(f.ftype, v, f.label)
    return cfg


def required_missing(cfg: Dict[str, Any], step: Optional[str] = None) -> List[str]:
    """返回指定步骤（None=全部）缺失/非法的必填项中文说明列表，为空即校验通过。"""
    problems: List[str] = []
    fields = (CONFIG_FIELDS if step is None
              else [f for f in CONFIG_FIELDS if f.step == step])
    for f in fields:
        value = cfg.get(f.key)
        if f.required and value in (None, ""):
            problems.append(f"[{step_label(f.step)}] {f.label} 未填写：{f.help}")
    # 第 3 步起做格式强校验
    name = str(cfg.get("function_name") or "")
    if name and not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", name):
        problems.append(f"[{step_label(STEP_FUNCTION)}] 函数名不合法："
                        "需字母开头、1~64 位，仅含字母/数字/_/-")
    image = str(cfg.get("image_url") or "")
    if image and re.search(r"\s", image):
        problems.append(f"[{step_label(STEP_FUNCTION)}] 镜像地址含空白字符，请检查格式")
    return problems


# ═══════════════════════════════════════════════════════════════════════════
# 基础工具
# ═══════════════════════════════════════════════════════════════════════════
def _log(msg: str) -> None:
    print(f"[provision] {msg}", flush=True)


def _to_map(resp: Any) -> Dict[str, Any]:
    body = getattr(resp, "body", None)
    if body is None:
        return {}
    try:
        return body.to_map()
    except AttributeError:
        return json.loads(json.dumps(body, default=str))


def _err_code(ex: Exception) -> str:
    """SDK 异常中的服务端错误码（TeaError.code）。"""
    return str(getattr(ex, "code", "") or "")


def _err_status(ex: Exception) -> int:
    """SDK 异常中的 HTTP 状态码（TeaError.status_code）。"""
    return int(getattr(ex, "status_code", 0) or 0)


def _wait_until(desc: str, poll, created: Optional[Dict[str, Any]] = None,
                timeout: int = 600, interval: int = 5) -> None:
    """轮询直到 poll() 返回真值或超时；超时抛 ProvisionError。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if poll():
            _log(f"✓ {desc} 就绪")
            return
        time.sleep(interval)
    raise ProvisionError(f"等待 {desc} 就绪超时（>{timeout}s）", created)


# ═══════════════════════════════════════════════════════════════════════════
# 第 1 步：账号凭证 / 身份校验 / 服务关联角色
# ═══════════════════════════════════════════════════════════════════════════
_FC_SLR_ROLE_NAME = "AliyunServiceRoleForFC"
_FC_SLR_SERVICE = "fc.aliyuncs.com"


def assume_role(cfg: Dict[str, Any]) -> Dict[str, str]:
    """平台 AK AssumeRole -> 目标账号 STS 临时凭证（每步自包含调用）。"""
    sts_client = StsClient(TeaConfig(
        access_key_id=cfg["platform_access_key_id"],
        access_key_secret=cfg["platform_access_key_secret"],
        endpoint="sts.aliyuncs.com",
    ))
    _log(f"AssumeRole: {cfg['assume_role_arn']} (session={cfg['role_session_name']})")
    try:
        resp = sts_client.assume_role(sts_models.AssumeRoleRequest(
            role_arn=cfg["assume_role_arn"],
            role_session_name=cfg["role_session_name"],
            duration_seconds=3600,
        ))
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(
            f"AssumeRole 失败，请检查平台 AK/SK 与被扮演角色 ARN：{ex}"
        ) from ex
    creds = resp.body.credentials
    return {
        "access_key_id": creds.access_key_id,
        "access_key_secret": creds.access_key_secret,
        "security_token": creds.security_token,
    }


def _caller_identity(creds: Dict[str, str]) -> Dict[str, str]:
    """用 STS 凭证确认实际身份（账号 ID / ARN），用于归属校验。"""
    sts_client = StsClient(TeaConfig(
        access_key_id=creds["access_key_id"],
        access_key_secret=creds["access_key_secret"],
        security_token=creds.get("security_token"),
        endpoint="sts.aliyuncs.com",
    ))
    body = sts_client.get_caller_identity(
        sts_models.GetCallerIdentityRequest()
    ).body
    return {
        "account_id": getattr(body, "account_id", "") or "",
        "arn": getattr(body, "arn", "") or "",
        "principal_id": getattr(body, "principal_id", "") or "",
    }


def _build_clients(cfg: Dict[str, Any], creds: Dict[str, str]):
    """按目标账号地域构建 FC/VPC/ECS/RAM 客户端（均用 STS 临时凭证）。"""
    fc_endpoint = f"{cfg['target_account_id']}.{cfg['region']}.fc.aliyuncs.com"
    fc = FCClient(TeaConfig(
        access_key_id=creds["access_key_id"],
        access_key_secret=creds["access_key_secret"],
        security_token=creds.get("security_token"),
        endpoint=fc_endpoint,
    ))
    vpc = VpcClient(TeaConfig(
        access_key_id=creds["access_key_id"],
        access_key_secret=creds["access_key_secret"],
        security_token=creds.get("security_token"),
        endpoint="vpc.aliyuncs.com",
    ))
    ecs = EcsClient(TeaConfig(
        access_key_id=creds["access_key_id"],
        access_key_secret=creds["access_key_secret"],
        security_token=creds.get("security_token"),
        region_id=cfg["region"],
        endpoint=f"ecs.{cfg['region']}.aliyuncs.com",
    ))
    ram = RamClient(TeaConfig(
        access_key_id=creds["access_key_id"],
        access_key_secret=creds["access_key_secret"],
        security_token=creds.get("security_token"),
        endpoint="ram.aliyuncs.com",
    ))
    return fc, vpc, ecs, ram


def _ensure_fc_service_linked_role(ram: RamClient, auto_create: bool) -> Dict[str, str]:
    """幂等确保 AliyunServiceRoleForFC 就绪，返回状态摘要。

    FC 产品自 2024-08-27 起自动开通；函数挂 VPC / 拉镜像依赖该服务关联角色，
    缺失时（auto_create=True）调用 RAM CreateServiceLinkedRole 补建。
    """
    _log(f"检查 FC 服务关联角色 {_FC_SLR_ROLE_NAME} ...")
    summary = {"role_name": _FC_SLR_ROLE_NAME, "status": "unknown"}
    # 1) 探测：已存在直接返回
    try:
        ram.get_role(ram_models.GetRoleRequest(role_name=_FC_SLR_ROLE_NAME))
        summary["status"] = "exists"
        _log(f"✓ 服务关联角色 {_FC_SLR_ROLE_NAME} 已存在")
        return summary
    except Exception as ex:  # noqa: BLE001
        code = _err_code(ex)
        if not any(k in code for k in
                   ("NoSuchEntity", "EntityNotExist", "NotFound",
                    "NoPermission", "Forbidden")):
            raise ProvisionError(f"查询服务关联角色失败: {ex}") from ex
        if not any(k in code for k in ("NoSuchEntity", "EntityNotExist", "NotFound")):
            _log("GetRole 无权限，改用 CreateServiceLinkedRole 幂等创建 ...")
    # 2) 缺失：按 auto_create 决定是否补建
    if not auto_create:
        raise ProvisionError(
            f"服务关联角色 {_FC_SLR_ROLE_NAME} 不存在，且 auto_create_slr=false。"
            "请开启自动创建，或让目标账号管理员登录一次 FC 3.0 控制台后重试。"
        )
    try:
        ram.create_service_linked_role(ram_models.CreateServiceLinkedRoleRequest(
            service_name=_FC_SLR_SERVICE,
            description="Function Compute service-linked role "
                        "(auto-created by provision_image_function.py)",
        ))
        summary["status"] = "created"
        _log(f"✓ 已自动创建 {_FC_SLR_ROLE_NAME}，等待其在鉴权链路生效 ...")
        time.sleep(10)  # 新角色写入鉴权链路需要数秒
        return summary
    except Exception as ex:  # noqa: BLE001
        code = _err_code(ex)
        status = _err_status(ex)
        if "AlreadyExists" in code or status == 409:
            summary["status"] = "exists"
            _log(f"✓ 服务关联角色 {_FC_SLR_ROLE_NAME} 已存在")
            return summary
        if "NoPermission" in code or "Forbidden" in code or status == 403:
            raise ProvisionError(
                f"自动创建 {_FC_SLR_ROLE_NAME} 被拒（权限不足: {ex}）\n"
                "  请给被扮演角色附加 AliyunRAMFullAccess，或最小策略:\n"
                '    {"Action": ["ram:GetRole", "ram:CreateServiceLinkedRole"],\n'
                '     "Resource": "*",\n'
                '     "Condition": {"StringEquals": {"ram:ServiceName": "fc.aliyuncs.com"}}}\n'
                "  或由目标账号管理员登录一次 FC 3.0 控制台后重试。"
            ) from ex
        raise ProvisionError(f"创建服务关联角色失败: {ex}") from ex


def validate_account(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """向导第 1 步：校验账号信息与角色（AssumeRole + 身份归属 + SLR 就绪）。

    Args:
        cfg: 规范化后的配置（build_config 输出）。

    Returns:
        摘要 dict（不含任何 Secret），供面板展示与保存。

    Raises:
        ProvisionError: 必填缺失、角色不可达、账号不匹配或 SLR 无法就绪。
    """
    problems = required_missing(cfg, STEP_ACCOUNT)
    if problems:
        raise ProvisionError("第 1 步（账号与角色）校验未通过：\n  - " + "\n  - ".join(problems))

    creds = assume_role(cfg)  # 失败已在内部转为 ProvisionError

    identity = _caller_identity(creds)
    account_id = identity["account_id"]
    if account_id != cfg["target_account_id"]:
        raise ProvisionError(
            f"角色归属账号 {account_id} 与填写的目标账号 ID "
            f"{cfg['target_account_id']} 不一致，请检查 ASSUME_ROLE_ARN 与账号 ID。"
        )

    slr = {}
    if cfg["auto_create_slr"]:
        # 权限不足等场景会抛出带指引的 ProvisionError，直接向上传播
        _, _vpc, _ecs, ram = _build_clients(cfg, creds)
        slr = _ensure_fc_service_linked_role(ram, True)

    _log("✓ 账号与角色校验通过")
    return {
        "step": STEP_ACCOUNT,
        "account_id": account_id,
        "region": cfg["region"],
        "role_arn": cfg["assume_role_arn"],
        "assumed_arn": identity["arn"],
        "sts_access_key_id": creds["access_key_id"],  # 临时凭证非敏感
        "slr": slr,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 第 2 步：VPC 网络链路（自动创建, 省钱方案）
# ═══════════════════════════════════════════════════════════════════════════
def _pick_zone(vpc: VpcClient, cfg: Dict[str, Any]) -> str:
    """可用区优先用 zone_id，留空自动取该地域第一个可用区。"""
    if cfg["zone_id"]:
        return cfg["zone_id"]
    resp = vpc.describe_zones(vpc_models.DescribeZonesRequest(region_id=cfg["region"]))
    zones = _to_map(resp).get("Zones", {}).get("Zone", []) or []
    if not zones:
        raise ProvisionError("DescribeZones 未返回任何可用区")
    zone = zones[0]["ZoneId"]
    _log(f"zone_id 未指定，自动选择可用区: {zone} "
         "(若后续函数创建报可用区不支持，请填写 zone_id)")
    return zone


def _create_vpc_chain(vpc: VpcClient, ecs: EcsClient, cfg: Dict[str, Any],
                      created: Dict[str, Any]) -> Dict[str, Any]:
    """创建 VPC -> 交换机 -> 安全组 -> NAT -> EIP -> 绑定 -> SNAT。"""
    region = cfg["region"]
    desc = "container image function with fixed egress IP (created by provision)"

    # ---- VPC ----
    _log("创建 VPC ...")
    try:
        vpc_id = _to_map(vpc.create_vpc(vpc_models.CreateVpcRequest(
            region_id=region, cidr_block=cfg["vpc_cidr"],
            vpc_name="fc-fixed-egress-vpc", description=desc,
        ))).get("VpcId")
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"创建 VPC 失败: {ex}", created) from ex
    if not vpc_id:
        raise ProvisionError("CreateVpc 未返回 VpcId", created)
    created["vpc_id"] = vpc_id

    def _vpc_ok() -> bool:
        m = _to_map(vpc.describe_vpcs(vpc_models.DescribeVpcsRequest(
            region_id=region, vpc_id=vpc_id)))
        vpcs = m.get("Vpcs", {}).get("Vpc") or []
        return bool(vpcs) and vpcs[0].get("Status") == "Available"

    _wait_until("VPC", _vpc_ok, created)

    # ---- 交换机 ----
    try:
        zone_id = _pick_zone(vpc, cfg)
        _log(f"创建交换机 (可用区 {zone_id}) ...")
        v_switch_id = _to_map(vpc.create_v_switch(vpc_models.CreateVSwitchRequest(
            region_id=region, vpc_id=vpc_id, zone_id=zone_id,
            cidr_block=cfg["vswitch_cidr"], v_switch_name="fc-fixed-egress-vsw",
            description=desc,
        ))).get("VSwitchId")
    except ProvisionError:
        raise
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"创建交换机失败: {ex}", created) from ex
    if not v_switch_id:
        raise ProvisionError("CreateVSwitch 未返回 VSwitchId", created)
    created["v_switch_id"] = v_switch_id
    created["zone_id"] = zone_id

    def _vsw_ok() -> bool:
        m = _to_map(vpc.describe_v_switches(vpc_models.DescribeVSwitchesRequest(
            region_id=region, vpc_id=vpc_id)))
        vsws = m.get("VSwitches", {}).get("VSwitch") or []
        return any(s.get("VSwitchId") == v_switch_id
                   and s.get("Status") == "Available" for s in vsws)

    _wait_until("交换机", _vsw_ok, created)

    # ---- 安全组（ECS API, 出方向默认放行）----
    _log("创建安全组 ...")
    try:
        sg_id = _to_map(ecs.create_security_group(ecs_models.CreateSecurityGroupRequest(
            region_id=region, vpc_id=vpc_id,
            security_group_name="fc-fixed-egress-sg", description=desc,
        ))).get("SecurityGroupId")
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"创建安全组失败: {ex}", created) from ex
    if not sg_id:
        raise ProvisionError("CreateSecurityGroup 未返回 SecurityGroupId", created)
    created["security_group_id"] = sg_id

    # ---- 增强型按量 NAT（按CU计费 PayByLcu, 最省）----
    _log("创建增强型 NAT 网关 (PostPaid / PayByLcu) ...")
    try:
        nat_map = _to_map(vpc.create_nat_gateway(vpc_models.CreateNatGatewayRequest(
            region_id=region, vpc_id=vpc_id, v_switch_id=v_switch_id,
            nat_type="Enhanced", instance_charge_type="PostPaid",
            internet_charge_type="PayByLcu", network_type="internet",
            nat_gateway_name="fc-fixed-egress-nat", description=desc,
        )))
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"创建 NAT 网关失败: {ex}", created) from ex
    nat_id = nat_map.get("NatGatewayId")
    if not nat_id:
        raise ProvisionError("CreateNatGateway 未返回 NatGatewayId", created)
    created["nat_gateway_id"] = nat_id
    snat_table_id = ((nat_map.get("SnatTableIds") or {}).get("SnatTableId") or [None])[0]
    if not snat_table_id:
        raise ProvisionError("CreateNatGateway 未返回 SnatTableId", created)
    created["snat_table_id"] = snat_table_id

    def _nat_ok() -> bool:
        m = _to_map(vpc.describe_nat_gateways(vpc_models.DescribeNatGatewaysRequest(
            region_id=region, nat_gateway_id=nat_id)))
        nats = m.get("NatGateways", {}).get("NatGateway") or []
        return bool(nats) and nats[0].get("Status") == "Available"

    _wait_until("NAT 网关", _nat_ok, created)

    # ---- EIP（按量 / 按流量 / 带宽上限）----
    _log(f"申请 EIP (PostPaid / PayByTraffic / {cfg['eip_bandwidth_mbps']}Mbps) ...")
    try:
        eip_map = _to_map(vpc.allocate_eip_address(vpc_models.AllocateEipAddressRequest(
            region_id=region, instance_charge_type="PostPaid",
            internet_charge_type="PayByTraffic", bandwidth=cfg["eip_bandwidth_mbps"],
            name="fc-fixed-egress-eip", description=desc,
        )))
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"申请 EIP 失败: {ex}", created) from ex
    allocation_id = eip_map.get("AllocationId")
    eip_address = eip_map.get("EipAddress")
    if not allocation_id or not eip_address:
        raise ProvisionError("AllocateEipAddress 未返回 AllocationId/EipAddress", created)
    created["eip_allocation_id"] = allocation_id
    created["eip_address"] = eip_address

    def _eip_ok() -> bool:
        m = _to_map(vpc.describe_eip_addresses(vpc_models.DescribeEipAddressesRequest(
            region_id=region, allocation_id=allocation_id)))
        eips = m.get("EipAddresses", {}).get("EipAddress") or []
        return bool(eips) and eips[0].get("Status") == "Available"

    _wait_until("EIP", _eip_ok, created)

    # ---- 绑定 EIP -> NAT ----
    _log(f"绑定 EIP {eip_address} 到 NAT ...")
    try:
        vpc.associate_eip_address(vpc_models.AssociateEipAddressRequest(
            region_id=region, allocation_id=allocation_id,
            instance_id=nat_id, instance_type="Nat",
        ))
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"绑定 EIP 到 NAT 失败: {ex}", created) from ex

    def _assoc_ok() -> bool:
        m = _to_map(vpc.describe_eip_addresses(vpc_models.DescribeEipAddressesRequest(
            region_id=region, allocation_id=allocation_id)))
        eips = m.get("EipAddresses", {}).get("EipAddress") or []
        return bool(eips) and eips[0].get("Status") == "InUse"

    _wait_until("EIP->NAT 绑定", _assoc_ok, created)

    # ---- SNAT: 交换机网段 -> EIP（函数出公网即固定为该 EIP）----
    _log("创建 SNAT 条目 ...")
    try:
        snat_map = _to_map(vpc.create_snat_entry(vpc_models.CreateSnatEntryRequest(
            region_id=region, snat_table_id=snat_table_id,
            source_v_switch_id=v_switch_id, snat_ip=eip_address,
            snat_entry_name="fc-fixed-egress-snat",
        )))
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"创建 SNAT 条目失败: {ex}", created) from ex
    snat_entry_id = snat_map.get("SnatEntryId")
    if snat_entry_id:
        created["snat_entry_id"] = snat_entry_id

    return dict(created)


def ensure_network(cfg: Dict[str, Any],
                   existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """向导第 2 步：创建 VPC 全链路（含固定公网出口）。

    Args:
        cfg: 规范化配置（需含第 1 步与第 2 步字段）。
        existing: 若传入已建好的网络结果（含 vpc_id），直接复用返回（幂等），
                  供面板“沿用已建网络/失败重试”场景。

    Returns:
        网络资源 dict：vpc_id / v_switch_id / zone_id / security_group_id /
        nat_gateway_id / snat_table_id / eip_allocation_id / eip_address / snat_entry_id。

    Raises:
        ProvisionError: 任一资源创建失败（created 中带已建部分清单）。
    """
    problems = required_missing(cfg, STEP_ACCOUNT) + required_missing(cfg, STEP_NETWORK)
    if problems:
        raise ProvisionError("第 2 步（VPC 网络链路）依赖配置缺失：\n  - " + "\n  - ".join(problems))
    if existing and existing.get("vpc_id"):
        _log("已提供既有网络资源（vpc_id=" + str(existing["vpc_id"]) + "），直接复用")
        return dict(existing)

    creds = assume_role(cfg)
    _, vpc_client, ecs_client, _ram = _build_clients(cfg, creds)

    created: Dict[str, Any] = {}
    try:
        net = _create_vpc_chain(vpc_client, ecs_client, cfg, created)
    except ProvisionError:
        raise  # created 已随异常携带
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"创建 VPC 网络链路失败: {ex}", created) from ex

    _log(f"✓ VPC 网络链路就绪，固定公网出口 EIP: {net.get('eip_address')}")
    return net


# ═══════════════════════════════════════════════════════════════════════════
# 第 3 步：创建容器镜像函数（custom-container + VPC + 会话亲和）+ HTTP 触发器
# ═══════════════════════════════════════════════════════════════════════════
def _function_exists(fc_client: FCClient, function_name: str) -> bool:
    try:
        fc_client.get_function(function_name)
        return True
    except Exception as ex:  # noqa: BLE001 —— SDK 网络层异常形态不一
        if _err_status(ex) == 404 or "FunctionNotFound" in _err_code(ex):
            return False
        raise ProvisionError(f"查询函数 {function_name} 失败: {ex}") from ex


def _create_function(fc_client: FCClient, cfg: Dict[str, Any],
                     net: Dict[str, Any]) -> Dict[str, Any]:
    function_name = cfg["function_name"]
    if _function_exists(fc_client, function_name):
        raise ProvisionError(
            f"函数名 {function_name} 已存在（冲突策略=报错，不做更新）。"
            "如需重建请先在控制台删除该函数，或修改 function_name 后重试。")

    registry_config = None
    if cfg["image_registry_username"] and cfg["image_registry_password"]:
        registry_config = fc_models.RegistryConfig(
            auth_config=fc_models.RegistryAuthConfig(
                user_name=cfg["image_registry_username"],
                password=cfg["image_registry_password"],
            )
        )

    # HeaderField 会话亲和配置（JSON 字符串）
    session_affinity_config = json.dumps({
        "affinityHeaderFieldName": cfg["affinity_header_field_name"],
        "sessionConcurrencyPerInstance": cfg["session_concurrency_per_instance"],
        "sessionTTLInSeconds": cfg["session_ttl_seconds"],
        "sessionIdleTimeoutInSeconds": cfg["session_idle_timeout_seconds"],
        "disableSessionIdReuse": cfg["disable_session_id_reuse"],
    }, ensure_ascii=False)

    # exec_role 留空时 role 不填，FC 自动使用服务关联角色 AliyunServiceRoleForFC
    exec_role = cfg["function_exec_role_arn"] or None

    body = fc_models.CreateFunctionInput(
        function_name=function_name,
        runtime="custom-container",
        description="container image function with fixed egress IP (created by provision)",
        custom_container_config=fc_models.CustomContainerConfig(
            image=cfg["image_url"],
            port=cfg["container_port"],
            registry_config=registry_config,
        ),
        # 规格
        cpu=cfg["cpu_vcores"],
        memory_size=cfg["memory_size_mb"],
        timeout=cfg["timeout_seconds"],
        disk_size=cfg["disk_size_mb"],
        # 固定公网出口: 挂用户 VPC + 禁直连公网, 出公网只走 NAT/EIP
        vpc_config=fc_models.VPCConfig(
            vpc_id=net["vpc_id"],
            v_switch_ids=[net["v_switch_id"]],
            security_group_id=net["security_group_id"],
            role=exec_role,
        ),
        internet_access=False,
        role=exec_role,
        # Header 会话亲和
        session_affinity="HEADER_FIELD",
        session_affinity_config=session_affinity_config,
    )
    _log(f"创建函数 {function_name} (镜像 {cfg['image_url']}) ...")
    try:
        resp = fc_client.create_function(fc_models.CreateFunctionRequest(body=body))
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"创建函数失败: {ex}") from ex
    return _to_map(resp)


def _create_trigger(fc_client: FCClient, cfg: Dict[str, Any],
                    function_name: str) -> Dict[str, Any]:
    trigger_config = json.dumps({
        "methods": cfg["trigger_methods"],
        "authType": "function",  # AK 签名鉴权
        "disableURLInternet": False,
    }, ensure_ascii=False)
    _log(f"创建 HTTP 触发器 {cfg['trigger_name']} (authType=function) ...")
    try:
        resp = fc_client.create_trigger(
            function_name,
            fc_models.CreateTriggerRequest(body=fc_models.CreateTriggerInput(
                trigger_name=cfg["trigger_name"],
                trigger_type="http",
                trigger_config=trigger_config,
                qualifier="LATEST",
                description="signed http trigger",
            )),
        )
    except Exception as ex:  # noqa: BLE001
        raise ProvisionError(f"创建 HTTP 触发器失败: {ex}") from ex
    return _to_map(resp)


def deploy_function(cfg: Dict[str, Any],
                    net: Dict[str, Any]) -> Dict[str, Any]:
    """向导第 3 步：创建镜像函数 + 签名 HTTP 触发器（依赖第 2 步网络）。

    Args:
        cfg: 规范化配置（需含第 1、3 步字段与第 2 步网络参数）。
        net: ensure_network() 的返回结果（含 vpc_id 等）。

    Returns:
        部署结果 dict：function_name / trigger_name / url_internet /
        eip_address / affinity_header。

    Raises:
        ProvisionError: 配置缺失、无网络资源、函数名冲突或创建失败。
    """
    problems = (required_missing(cfg, STEP_ACCOUNT)
                + required_missing(cfg, STEP_NETWORK)
                + required_missing(cfg, STEP_FUNCTION))
    if problems:
        raise ProvisionError("第 3 步（函数与触发器）依赖配置缺失：\n  - " + "\n  - ".join(problems))
    if not (net or {}).get("vpc_id"):
        raise ProvisionError(
            "缺少 VPC 网络资源：请先执行第 2 步 ensure_network() 并把返回结果作为 net 传入。")

    creds = assume_role(cfg)
    fc_client, _vpc, _ecs, _ram = _build_clients(cfg, creds)

    fn = _create_function(fc_client, cfg, net)
    function_name = fn.get("functionName") or cfg["function_name"]
    trig = _create_trigger(fc_client, cfg, function_name)

    url_internet = ((trig.get("httpTrigger") or {}).get("urlInternet")
                    or (trig.get("triggers") or [{}])[0].get("urlInternet") or "")
    _log(f"✓ 函数 {function_name} 部署完成")
    return {
        "step": STEP_FUNCTION,
        "function_name": function_name,
        "trigger_name": cfg["trigger_name"],
        "url_internet": url_internet,
        "eip_address": (net or {}).get("eip_address", ""),
        "affinity_header": cfg["affinity_header_field_name"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 一键编排
# ═══════════════════════════════════════════════════════════════════════════
def provision_all(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """一键执行全部三步（等价于面板向导全部提交）。cfg 须含所有必填字段。"""
    account = validate_account(cfg)
    net = ensure_network(cfg)
    function = deploy_function(cfg, net)
    return {
        "steps": [account["step"], net["step"] if "step" in net else STEP_NETWORK,
                  function["step"]],
        "account": account,
        "network": net,
        "function": function,
    }


def summary_text(result: Dict[str, Any]) -> str:
    """把步骤结果渲染为易读文本（CLI / 面板结果页可直接展示）。"""
    func = result.get("function", {})
    net = result.get("network", {})
    lines = [
        "=" * 60,
        "部署完成 ✔",
        "=" * 60,
        f"目标账号     : {result.get('account', {}).get('account_id', '')}",
        f"地域         : {result.get('account', {}).get('region', '')}",
        f"固定出口 EIP : {net.get('eip_address', '')}",
        f"函数名       : {func.get('function_name', '')}",
        f"触发器       : {func.get('trigger_name', '')}",
    ]
    if func.get("url_internet"):
        lines.append(f"公网访问地址 : {func['url_internet']}")
        lines.append("调用方式     : AK 签名鉴权(authType=function)，请求头携带 "
                     f"'{func.get('affinity_header', '')}: <会话ID>' 命中同一实例会话。")
    lines.append("白名单提示   : 目标网站请放行上方固定出口 EIP；"
                 "NAT/EIP 按量计费，不用时可删除。")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# DB 桥接（供 Web 面板读取/保存配置）
# ═══════════════════════════════════════════════════════════════════════════
async def load_config_from_db() -> Dict[str, Any]:
    """从 db.system_config_db 读取全部已注册配置键并规范化为 cfg（不回滚默认）。"""
    from db.system_config_db import SystemConfigDB

    raw = await SystemConfigDB.get_many(CONFIG_KEYS)
    return build_config(raw)


def _to_storage(value: Any) -> str:
    """配置值转 DB 存储字符串：list/dict 用 JSON，bool 用 true/false，其余 str()。"""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


async def save_config_to_db(values: Dict[str, Any]) -> None:
    """把面板填写的原始值批量写回 db（仅接受 CONFIG_KEYS 中的键，自动转存储格式）。"""
    from db.system_config_db import SystemConfigDB

    clean = {f.key: _to_storage(values[f.key])
             for f in CONFIG_FIELDS if f.key in values}
    await SystemConfigDB.set_many(clean)


# ═══════════════════════════════════════════════════════════════════════════
# 命令行入口（调试/运维：从 db 读取配置一键执行）
# ═══════════════════════════════════════════════════════════════════════════
async def _cli() -> int:
    from db.init_db import init_db

    await init_db()  # 建表并写入缺失的默认配置（幂等）

    cfg = await load_config_from_db()
    problems = required_missing(cfg)
    if problems:
        print("[provision] 以下必填配置缺失（请在 DB 系统配置表中填写后重试）：",
              file=sys.stderr)
        for p in problems:
            print(f"    - {p}", file=sys.stderr)
        return 2

    try:
        result = provision_all(cfg)
    except ProvisionError as ex:
        print(f"\n[provision] ✗ {ex}", file=sys.stderr)
        if ex.created:
            print("[provision] 已创建资源清单（不自动回滚，请人工确认是否需要清理）:",
                  file=sys.stderr)
            for k, v in ex.created.items():
                print(f"    {k}: {v}", file=sys.stderr)
        return 1
    print("\n" + summary_text(result))
    return 0


def main() -> None:
    """CLI 入口：python fc/provision_image_function.py"""
    import asyncio

    sys.exit(asyncio.run(_cli()))


if __name__ == "__main__":
    main()
