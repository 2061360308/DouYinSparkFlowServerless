"""调度层：把「仅带 task_id」的触发器注册到各平台。

按 ``target_env`` 分派：
- ``linux``   → 写入 crontab（每任务一段带 ``CRON_TZ=Asia/Shanghai`` 的标记块）。
- ``windows`` → 生成计划任务 XML 并 ``schtasks /Create /XML``（choice A）。
- ``fc``      → 阿里云 EventBridge 定时调度 → FC（控制台显式传入安装配置）。

设计：``build_*``（纯函数，产出待写入的构件，可单测）+ ``register_*/unregister_*``
（执行副作用）。触发器以 ``task_id`` 命名/标记；云端更新优先，不存在才创建。
唤醒后统一执行 ``python -m core.task.run --task-id <task_id>``。
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import cron_utils

# 仓库根目录（core 的上级），Linux 触发命令切到此目录以保证 -m core.task.run 可导入
_REPO_DIR = Path(__file__).resolve().parent.parent.parent

# Windows 侧 python 可执行文件与工作目录（服务端生成 XML，故通过环境变量指定目标机路径）
_WINDOWS_PYTHON = os.getenv("TASK_WINDOWS_PYTHON", "python")
_WINDOWS_WORKDIR = os.getenv("TASK_WINDOWS_WORKDIR", "")

_BEGIN = "# >>> task:{tid} >>>"
_END = "# <<< task:{tid} <<<"


# ---------------------------------------------------------------------------
# Linux crontab
# ---------------------------------------------------------------------------
def build_linux_block(task: dict) -> str:
    """构造某任务在 crontab 中的标记块（含 CRON_TZ 与首尾标记）。"""
    tid = task["task_id"]
    cmd = (
        f"cd {shlex.quote(str(_REPO_DIR))} && "
        f"{shlex.quote(sys.executable)} -m core.task.run --task-id {shlex.quote(tid)}"
    )
    return "\n".join([
        _BEGIN.format(tid=tid),
        "CRON_TZ=Asia/Shanghai",
        f"{task['cron_expr']} {cmd}",
        _END.format(tid=tid),
    ])


def _read_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def _write_crontab(content: str) -> None:
    proc = subprocess.run(["crontab", "-"], input=content, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"写入 crontab 失败：{proc.stderr.strip()}")


def _strip_block(content: str, tid: str) -> str:
    begin, end = _BEGIN.format(tid=tid), _END.format(tid=tid)
    out, skip = [], False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == begin:
            skip = True
            continue
        if stripped == end:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out)


def register_linux(task: dict) -> None:
    if shutil.which("crontab") is None:
        raise RuntimeError("未找到 crontab 命令，无法注册 Linux 定时任务")
    content = _strip_block(_read_crontab(), task["task_id"])
    prefix = content.rstrip("\n") + "\n" if content.strip() else ""
    _write_crontab(prefix + build_linux_block(task) + "\n")


def unregister_linux(task_id: str) -> None:
    if shutil.which("crontab") is None:
        return
    content = _strip_block(_read_crontab(), task_id)
    _write_crontab(content.rstrip("\n") + "\n" if content.strip() else "")


# ---------------------------------------------------------------------------
# Windows 计划任务（schtasks /Create /XML）
# ---------------------------------------------------------------------------
def build_windows_xml(task: dict) -> str:
    """生成该任务的计划任务 XML。"""
    return cron_utils.to_windows_xml(
        task["cron_expr"],
        _WINDOWS_PYTHON,
        f"-m core.task.run --task-id {task['task_id']}",
        description=f"task {task['task_id']} ({task['event_category']})",
        workdir=_WINDOWS_WORKDIR,
    )


def register_windows(task: dict) -> None:
    xml = build_windows_xml(task)
    if shutil.which("schtasks") is None:
        raise RuntimeError("当前系统无 schtasks，Windows 计划任务需在 Windows 上注册")
    tmp = tempfile.NamedTemporaryFile("wb", suffix=".xml", delete=False)
    try:
        tmp.write(xml.encode("utf-16"))  # schtasks 要求 UTF-16
        tmp.close()
        proc = subprocess.run(
            ["schtasks", "/Create", "/TN", task["task_id"], "/XML", tmp.name, "/F"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"schtasks 创建失败：{proc.stderr.strip()}")
    finally:
        os.unlink(tmp.name)


def unregister_windows(task_id: str) -> None:
    if shutil.which("schtasks") is None:
        return
    subprocess.run(
        ["schtasks", "/Delete", "/TN", task_id, "/F"], capture_output=True, text=True
    )


# ---------------------------------------------------------------------------
# 阿里云 EventBridge 定时事件源 → 总线 → 规则(acs.api.destination) → FC 触发器
# ---------------------------------------------------------------------------
# ROS 只建"骨架"(总线+规则+ApiDestination+Connection+函数+触发器)；这里为每个续火
# 任务动态增删一个"定时事件源"(name=task_id, cron, data={task_id})，事件进总线后由
# 那条静态规则统一投递到任务执行器。
#
# 凭证/地域/总线经环境变量(服务端进程注入)：
#   ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET (或 SPARK_ALIYUN_AK/SK)
#   SPARK_ALIYUN_REGION(默认 cn-hangzhou) / SPARK_EVENTBRIDGE_BUS(默认 default) /
#   SPARK_EVENTBRIDGE_TZ(默认 GMT+08:00)
# 依赖: alibabacloud-eventbridge20200401


def _eb_bus_name() -> str:
    return os.getenv("SPARK_EVENTBRIDGE_BUS", "default")


def _eb_client(config: dict | None = None):
    """构造 EventBridge OpenAPI 客户端（凭证走环境变量）。"""
    from alibabacloud_eventbridge20200401.client import Client
    from alibabacloud_tea_openapi.models import Config

    region = config['region'] if config is not None else os.getenv("SPARK_ALIYUN_REGION", "cn-hangzhou")
    ak = config['platform_access_key_id'] if config is not None else os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID") or os.getenv("SPARK_ALIYUN_AK", "")
    sk = config['platform_access_key_secret'] if config is not None else os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET") or os.getenv("SPARK_ALIYUN_SK", "")
    if not ak or not sk:
        raise RuntimeError(
            "EventBridge 需要凭证：请设 ALIBABA_CLOUD_ACCESS_KEY_ID/ACCESS_KEY_SECRET"
        )
    return Client(Config(
        access_key_id=ak, access_key_secret=sk,
        endpoint=f"eventbridge.{region}.aliyuncs.com",
        # 海外网络(如 Vercel)到大陆链路延迟高，放宽连接/读取超时。
        connect_timeout=10000, read_timeout=30000,
    ))


def build_fc_schedule(task: dict, *, bus_name: str | None = None, time_zone: str | None = None) -> dict:
    """构造 EventBridge 定时事件源参数（纯函数，便于单测）。"""
    cron_utils.validate(task['cron_expr'])
    return {
        "event_source_name": task["task_id"],
        "event_bus_name": bus_name if bus_name is not None else _eb_bus_name(),
        # EventBridge uses seconds + standard five fields, not Quartz weekday numbering.
        "schedule": '0 ' + ' '.join(task['cron_expr'].split()),
        "time_zone": time_zone or os.getenv("SPARK_EVENTBRIDGE_TZ", "GMT+08:00"),
        "user_data": json.dumps({"task_id": task["task_id"]}, ensure_ascii=False),
    }


class EventSourceError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('EventBridge request failed')


def _eb_result(response):
    body = response.body
    if body.success is not True:
        raise EventSourceError(body.code)


def register_fc(task: dict, *, client=None, bus_name: str | None = None, time_zone: str | None = None) -> None:
    """先更新；仅在事件源确实不存在时创建，绝不吞掉权限或网络错误。"""
    from alibabacloud_eventbridge20200401 import models as eb

    params = build_fc_schedule(task, bus_name=bus_name, time_zone=time_zone)
    client = client or _eb_client()
    try:
        _eb_result(client.update_event_source(eb.UpdateEventSourceRequest(
            event_source_name=params['event_source_name'], event_bus_name=params['event_bus_name'],
            source_scheduled_event_parameters=eb.UpdateEventSourceRequestSourceScheduledEventParameters(
                schedule=params['schedule'], time_zone=params['time_zone'], user_data=params['user_data']),
        )))
        return
    except Exception as error:
        if getattr(error, 'code', None) != 'EventSourceNotExist':
            raise
    scheduled = eb.CreateEventSourceRequestSourceScheduledEventParameters(
        schedule=params["schedule"],
        time_zone=params["time_zone"],
        user_data=params["user_data"],
    )
    request = eb.CreateEventSourceRequest(
        event_source_name=params["event_source_name"],
        event_bus_name=params["event_bus_name"],
        source_scheduled_event_parameters=scheduled,
    )
    _eb_result(client.create_event_source(request))


def unregister_fc(task_id: str, *, client=None, bus_name: str | None = None) -> None:
    """删除任务对应的定时事件源(name=task_id)。"""
    from alibabacloud_eventbridge20200401 import models as eb

    client = client or _eb_client()
    request = eb.DeleteEventSourceRequest(
        event_source_name=task_id,
        event_bus_name=bus_name if bus_name is not None else _eb_bus_name(),
    )
    try:
        _eb_result(client.delete_event_source(request))
    except Exception as error:
        if getattr(error, 'code', None) != 'EventSourceNotExist':
            raise


# ---------------------------------------------------------------------------
# 分派门面
# ---------------------------------------------------------------------------
def register(task: dict) -> None:
    """按 target_env 注册触发器（幂等）。"""
    env = task.get("target_env", "linux")
    if env == "linux":
        return register_linux(task)
    if env == "windows":
        return register_windows(task)
    if env == "fc":
        return register_fc(task)
    raise ValueError(f"未知 target_env：{env}")


def unregister(task_id: str, target_env: str) -> None:
    """按 target_env 移除触发器（幂等）。"""
    if target_env == "linux":
        return unregister_linux(task_id)
    if target_env == "windows":
        return unregister_windows(task_id)
    if target_env == "fc":
        return unregister_fc(task_id)
    raise ValueError(f"未知 target_env：{target_env}")


def sync(task: dict) -> None:
    """按 enabled 决定注册或移除。"""
    if task.get("enabled"):
        register(task)
    else:
        unregister(task["task_id"], task.get("target_env", "linux"))
