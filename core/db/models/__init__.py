"""数据库模型包。

按业务域拆分到各子模块，统一在此处重新导出，方便上层按旧习惯使用：

    from core.db.models import User, SparkTask

所有 Tortoise 模型注册路径为 ``core.db.models.<module>``。
"""

from .account import (
    DouyinAccount,
    DouyinAccountIdentity,
    DouyinContactIdentity,
    DouyinConversation,
)
from .audit import AuditEvent, RateLimitAttempt
from .base import uuid_string
from .browser import BrowserInstance
from .invite import InviteCode, InviteCodeSecret
from .login import (
    DouyinLoginAction,
    DouyinLoginInput,
    DouyinLoginSession,
    ScanStatus,
)
from .quota import TaskQuotaGrant, TaskQuotaPolicy
from .scheduled import ScheduledTask
from .system import SystemConfig
from .task import SparkTask, SparkTaskTargetIdentity, TaskRun
from .user import EmailVerificationRequest, PendingRegistration, User, WebSession

__all__ = [
    # base
    "uuid_string",
    # system / browser
    "SystemConfig",
    "BrowserInstance",
    # user
    "User",
    "WebSession",
    "PendingRegistration",
    "EmailVerificationRequest",
    # account
    "DouyinAccount",
    "DouyinAccountIdentity",
    "DouyinConversation",
    "DouyinContactIdentity",
    # login
    "ScanStatus",
    "DouyinLoginSession",
    "DouyinLoginAction",
    "DouyinLoginInput",
    # quota
    "TaskQuotaPolicy",
    "TaskQuotaGrant",
    # invite
    "InviteCode",
    "InviteCodeSecret",
    # task
    "SparkTask",
    "SparkTaskTargetIdentity",
    "TaskRun",
    # audit / limit
    "AuditEvent",
    "RateLimitAttempt",
    # scheduled
    "ScheduledTask",
]
