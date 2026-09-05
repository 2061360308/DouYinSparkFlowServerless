"""调度层：把「仅带 task_id」的触发器注册到各平台。

按 ``target_env`` 分派：
- ``linux``   → 写入 crontab（每任务一段带 ``CRON_TZ=Asia/Shanghai`` 的标记块）。
- ``windows`` → 生成计划任务 XML 并 ``schtasks /Create /XML``（choice A）。
- ``fc``      → 阿里云 EventBridge 默认总线定时调度 → FC（需凭证，留待联调）。

设计：``build_*``（纯函数，产出待写入的构件，可单测）+ ``register_*/unregister_*``
（执行副作用）。触发器以 ``task_id`` 命名/标记，保证幂等（先删后建）。
唤醒后统一执行 ``python -m task.run --task-id <task_id>``。
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import cron_utils

# 仓库根目录（task 包的上级），Linux 触发命令切到此目录以保证 -m task.run 可导入
_REPO_DIR = Path(__file__).resolve().parent.parent

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
        f"{shlex.quote(sys.executable)} -m task.run --task-id {shlex.quote(tid)}"
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
        f"-m task.run --task-id {task['task_id']}",
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
# 阿里云 EventBridge 定时调度 → FC（免费链路，需凭证；留待云端联调）
# ---------------------------------------------------------------------------
def build_fc_schedule(task: dict) -> dict:
    """构造 EventBridge 定时调度所需参数（纯函数）。"""
    return {
        "rule_name": task["task_id"],
        "event_bus": "default",                       # 云服务专用总线，发布/推送 FC 免费
        "schedule": cron_utils.to_six_field(task["cron_expr"]),  # 6 段 cron
        "time_zone": "Asia/Shanghai",
        "payload": {"task_id": task["task_id"]},      # 事件载荷仅携带 task_id
    }


def register_fc(task: dict, *, client=None) -> None:
    """在默认总线创建定时调度规则、目标为 FC 函数（载荷携带 task_id）。

    需真实阿里云凭证，留待云端联调：请构造
    ``alibabacloud_eventbridge20200401`` 客户端并传入 ``client``，按
    ``build_fc_schedule(task)`` 的参数创建规则与 FC 目标。
    """
    schedule = build_fc_schedule(task)
    raise NotImplementedError(
        "EventBridge 定时调度需云端联调实现；"
        f"参数已就绪：{schedule}"
    )


def unregister_fc(task_id: str, *, client=None) -> None:
    raise NotImplementedError("EventBridge 规则删除需云端联调实现（DeleteRule rule_name=task_id）")


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
