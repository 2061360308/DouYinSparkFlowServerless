"""ROS (资源编排服务) 2019-09-10 OpenAPI 客户端封装。

供后端其他模块方便调用的三个核心能力:
1. create_stack(...)        -> 发起 CreateStack, 同步返回 stack_id (创建在后台进行)
2. get_stack_status(...)    -> 单次查询资源栈状态
   wait_stack_complete(...) -> 轮询直到终态: 成功返回/失败抛 StackFailedError(含失败资源原因)
3. get_trigger_url(...)     -> 创建完成后取 Web 触发器公网访问地址
   get_stack_outputs(...)   -> 全部 outputs (TriggerUrlInternet / TaskTriggerUrlInternet / FunctionName 等)

本模块为同步实现, 若后端基于异步框架 (FastAPI 等) 可直接用
asyncio.to_thread 包裹调用。

依赖:
    pip install alibabacloud_ros20190910

用法 (把父目录加入 sys.path / PYTHONPATH 后):
    export PYTHONPATH=$PYTHONPATH:/workspace/aliyunFC

    from install.ros_client import RosStackClient

    client = RosStackClient(
        region="cn-hangzhou",
        access_key_id="LTAI...",
        access_key_secret="...",
    )

    # ① 创建资源栈 (返回 stack_id, 不等待创建完成)
    stack_id = client.create_stack(
        template_body=Path("ros-template.yaml").read_text(encoding="utf-8"),
        stack_name="DouyinSpark",
        parameters={"Cpu": "1", "MemorySize": "1536"},
    )

    # ② 轮询创建状态 (失败抛异常, 自动带失败资源原因)
    client.wait_stack_complete(stack_id)

    # ③ 取触发器公网访问地址
    url = client.get_trigger_url(stack_id)
    # -> https://<function>-<uid>.cn-hangzhou.fcapp.run
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from Tea.exceptions import TeaException
from alibabacloud_ros20190910 import models as ros_models
from alibabacloud_ros20190910.client import Client as RosClient
from alibabacloud_tea_openapi.models import Config

logger = logging.getLogger(__name__)

DEFAULT_STACK_TIMEOUT_MINUTES = 60
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_WAIT_TIMEOUT = 1200.0
DEFAULT_PAGE_SIZE = 50

_CREATE_SUCCESS_STATUSES = {
    "CREATE_COMPLETE",
    "IMPORT_CREATE_COMPLETE",
}

_CREATE_IN_PROGRESS_STATUSES = {
    "CREATE_IN_PROGRESS",
    "CREATE_ROLLBACK_IN_PROGRESS",
    "CHECK_IN_PROGRESS",
    "REVIEW_IN_PROGRESS",
    "IMPORT_CREATE_IN_PROGRESS",
    "IMPORT_CREATE_ROLLBACK_IN_PROGRESS",
}


class RosStackError(Exception):
    """ROS API 调用失败 (鉴权/参数/网络等)。"""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        request_id: Optional[str] = None,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.request_id = request_id
        self.details = details

    def __str__(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"code={self.code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " | ".join(parts)


class StackFailedError(RosStackError):
    """资源栈创建失败/回滚, 携带失败资源事件供排查。"""

    def __init__(
        self,
        stack_id: str,
        status: str,
        status_reason: Optional[str],
        failed_events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        detail = "; ".join(
            f"{ev.get('LogicalResourceId')}({ev.get('ResourceType')}): "
            f"{ev.get('StatusReason')}"
            for ev in (failed_events or [])
        )
        message = f"stack {stack_id} creation failed with status={status}"
        if status_reason:
            message += f", reason={status_reason}"
        if detail:
            message += f", failed=[{detail}]"
        super().__init__(
            message,
            code=status,
            details={"status_reason": status_reason, "failed_events": failed_events},
        )
        self.stack_id = stack_id
        self.status = status
        self.status_reason = status_reason
        self.failed_events = failed_events or []


class StackWaitTimeoutError(RosStackError):
    """等待资源栈创建完成超时。"""

    def __init__(self, stack_id: str, timeout: float) -> None:
        super().__init__(
            f"wait stack {stack_id} complete timed out after {timeout:.0f}s"
        )
        self.stack_id = stack_id
        self.timeout = timeout


class RosStackClient:
    """ROS 资源栈客户端: 创建 / 查询状态 / 获取 outputs。"""

    def __init__(
        self,
        region: str,
        access_key_id: str,
        access_key_secret: str,
        security_token: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> None:
        """初始化 ROS 客户端。

        Args:
            region: 地域, 如 cn-hangzhou
            access_key_id / access_key_secret: AK/SK
            security_token: 使用 STS 临时凭证时传入
            endpoint: ROS 接入地址, 默认 f"ros.{region}.aliyuncs.com"
        """
        cfg = Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            security_token=security_token,
            endpoint=endpoint or f"ros.{region}.aliyuncs.com",
            connect_timeout=3000, read_timeout=10000,
        )
        self.client = RosClient(cfg)
        self.region = region

    # ------------------------------------------------------------------
    # ① 创建资源栈
    # ------------------------------------------------------------------
    def create_stack(
        self,
        template_body: str,
        stack_name: str,
        parameters: Optional[Dict[str, str]] = None,
        *,
        timeout_minutes: int = DEFAULT_STACK_TIMEOUT_MINUTES,
        disable_rollback: bool = False,
        client_token: Optional[str] = None,
    ) -> str:
        """发起创建资源栈, 同步返回 stack_id (不等待创建完成)。

        Args:
            template_body: ROS 模板原文 (YAML 字符串)
            stack_name: 资源栈名, 默认勿重复; 如 DouyinSpark
            parameters: 需覆盖的模板参数 {ParameterKey: ParameterValue};
                        未指定的参数沿用模板内 Default
            timeout_minutes: 栈创建超时(分钟), 默认 60
            disable_rollback: 创建失败是否禁用回滚
            client_token: 幂等令牌, 默认自动生成本次调用的全局唯一值

        Raises:
            RosStackError: CreateStack 同步失败 (参数校验/鉴权/配额等)
        """
        params = [
            ros_models.CreateStackRequestParameters(
                parameter_key=k,
                parameter_value=str(v),
            )
            for k, v in (parameters or {}).items()
        ]
        request = ros_models.CreateStackRequest(
            region_id=self.region,
            stack_name=stack_name,
            template_body=template_body,
            parameters=params or None,
            timeout_in_minutes=timeout_minutes,
            disable_rollback=disable_rollback,
            client_token=client_token or uuid.uuid4().hex,
        )
        logger.info(
            "create stack: name=%s region=%s params=%s",
            stack_name, self.region, sorted((parameters or {}).keys()),
        )
        try:
            resp = self.client.create_stack(request)
        except TeaException as exc:
            raise self._to_ros_error(exc) from exc
        body = resp.body
        stack_id = body.stack_id if body else None
        if not stack_id:
            raise RosStackError(
                f"create stack {stack_name} succeeded but got empty StackId",
                request_id=body.request_id if body else None,
            )
        logger.info("stack created: stack_id=%s", stack_id)
        return stack_id

    # ------------------------------------------------------------------
    # ② 查询状态 / 轮询
    # ------------------------------------------------------------------
    def get_stack_status(self, stack_id: str) -> Dict[str, Any]:
        """单次查询资源栈信息, 返回 GetStack 响应字段。

        常用字段: Status / StatusReason / Outputs / StackId / StackName /
        CreateTime / RegionId / Parameters 等。
        """
        request = ros_models.GetStackRequest(
            region_id=self.region,
            stack_id=stack_id,
        )
        try:
            resp = self.client.get_stack(request)
        except TeaException as exc:
            raise self._to_ros_error(exc) from exc
        body = resp.body
        if body is None:
            raise RosStackError(f"get stack {stack_id} returned empty body")
        return {
            k: v
            for k, v in body.to_map().items()
            if v is not None
        }

    def delete_stack(self, stack_id: str) -> None:
        """删除指定资源栈及其资源；调用方负责权限与明确确认。"""
        try:
            self.client.delete_stack(ros_models.DeleteStackRequest(
                region_id=self.region, stack_id=stack_id, retain_all_resources=False,
            ))
        except TeaException as exc:
            raise self._to_ros_error(exc) from exc

    def wait_stack_complete(
        self,
        stack_id: str,
        interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> Dict[str, Any]:
        """轮询资源栈直到创建终态。

        - 创建成功: 返回最终 GetStack 信息 (含 Outputs)
        - 创建失败/回滚: 抛 StackFailedError, 自动拉取失败资源事件
          (LogicalResourceId / ResourceType / StatusReason) 写入异常
        - 超时: 抛 StackWaitTimeoutError

        Args:
            interval: 轮询间隔秒
            timeout: 总等待上限秒
        """
        deadline = time.monotonic() + timeout
        while True:
            info = self.get_stack_status(stack_id)
            status = info.get("Status")
            if status in _CREATE_SUCCESS_STATUSES:
                logger.info("stack created complete: %s", stack_id)
                return info
            if status in _CREATE_IN_PROGRESS_STATUSES:
                if time.monotonic() >= deadline:
                    raise StackWaitTimeoutError(stack_id, timeout)
                time.sleep(interval)
                continue
            # 其余状态视为失败 / 回滚终态
            failed_events = self._list_failed_events(stack_id)
            raise StackFailedError(
                stack_id=stack_id,
                status=status or "UNKNOWN",
                status_reason=info.get("StatusReason"),
                failed_events=failed_events,
            )

    # ------------------------------------------------------------------
    # ③ 取 outputs / 触发器公网地址
    # ------------------------------------------------------------------
    def get_stack_outputs(self, stack_id: str) -> Dict[str, str]:
        """返回资源栈全部输出 {OutputKey: OutputValue}。

        本模板包含: TriggerUrlInternet / TriggerUrlIntranet / FunctionName /
        EventBusName / TaskFunctionName / TaskTriggerUrlInternet /
        ScheduleRuleName / ScheduleRuleARN / ApiDestinationName / ConnectionName。
        """
        info = self.get_stack_status(stack_id)
        outputs: Dict[str, str] = {}
        for item in info.get("Outputs") or []:
            if not isinstance(item, dict):
                continue
            key = item.get("OutputKey")
            value = item.get("OutputValue")
            if key is not None:
                outputs[key] = value
        return outputs

    def get_trigger_url(self, stack_id: str) -> str:
        """创建完成后取 Web 触发器公网访问地址 (Outputs 的 TriggerUrlInternet)。"""
        outputs = self.get_stack_outputs(stack_id)
        url = outputs.get("TriggerUrlInternet")
        if not url:
            raise RosStackError(
                f"stack {stack_id} has no TriggerUrlInternet output",
                details={"available_outputs": sorted(outputs)},
            )
        return url

    # ------------------------------------------------------------------
    # 内部: 错误转换 / 失败事件
    # ------------------------------------------------------------------
    @staticmethod
    def _to_ros_error(exc: TeaException) -> RosStackError:
        message = (
            f"ROS API error: {exc.message}"
            if exc.message
            else "ROS API error"
        )
        return RosStackError(
            message,
            code=exc.code,
            request_id=(exc.data or {}).get("RequestId")
            if isinstance(exc.data, dict)
            else None,
            details=exc.data,
        )

    def _list_failed_events(
        self,
        stack_id: str,
        max_events: int = 100,
    ) -> List[Dict[str, Any]]:
        """拉取创建过程中的失败/回滚资源事件, 便于定位失败原因。"""
        request = ros_models.ListStackEventsRequest(
            region_id=self.region,
            stack_id=stack_id,
            page_size=DEFAULT_PAGE_SIZE,
            page_number=1,
        )
        try:
            resp = self.client.list_stack_events(request)
        except TeaException as exc:
            logger.warning(
                "list_stack_events failed: code=%s message=%s",
                exc.code, exc.message,
            )
            return []
        body = resp.body
        events: List[Dict[str, Any]] = []
        for event in (body.events if body else None) or []:
            m = event.to_map()
            status = m.get("Status") or ""
            if status.endswith("FAILED") or "ROLLBACK" in status:
                events.append(m)
        return events[:max_events]
