"""FastAPI 响应模型（Pydantic V2）。

与 ``panel/src/api/console.ts`` 中的前端类型对应，用于：
- 生成完整的 OpenAPI/Swagger 文档
- 运行时校验响应结构
- 前后端接口契约对齐
"""

from __future__ import annotations

from pydantic import BaseModel


class UserInfo(BaseModel):
    id: str
    username: str
    role: str


class LoginResponse(BaseModel):
    csrf_token: str
    must_change_password: bool
    user: UserInfo


class MeResponse(BaseModel):
    user: UserInfo
    csrf_token: str
    is_admin: bool
    must_change_password: bool


class OkResponse(BaseModel):
    ok: bool


class HealthResponse(BaseModel):
    status: str


class AccountItem(BaseModel):
    id: str
    display_name: str
    validation_state: str


class ConversationItem(BaseModel):
    name: str
    sec_uid: str | None


class QuotaGrant(BaseModel):
    id: str
    amount: int
    label: str
    starts_at: str
    expires_at: str | None
    status: str
    days_remaining: int | None


class QuotaSummary(BaseModel):
    limit: int | None
    active_usage: int
    saved_usage: int
    max_saved_tasks: int
    grants: list[QuotaGrant]


class TaskItem(BaseModel):
    schedule_state: str = 'pending'
    schedule_error: str = ''
    id: str
    account_id: str | None
    target_name: str
    target_sec_uid: str
    send_time: str
    message_template: str
    enabled: bool
    next_run_at: str | None = None


class Availability(BaseModel):
    available: bool
    remaining: int
    suggestions: list[str]


class RunItem(BaseModel):
    id: str
    task_id: str
    target_name: str | None
    send_time: str | None
    scheduled_for: str | None
    status: str
    stage: str
    started_at: str | None
    finished_at: str | None
    error_code: str | None
    error_summary: str | None
    owner_username: str | None = None
    delivery_level: str = 'unknown'
    delivery_observed_at: str | None = None


class Pagination(BaseModel):
    page: int
    pages: int
    total: int
    has_previous: bool
    has_next: bool


class PlatformStatus(BaseModel):
    total: int
    success: int
    running: int
    pending: int
    failed: int
    worker_online: bool
    updated_at: str


class DashboardTaskItem(BaseModel):
    id: str
    target_name: str
    send_time: str
    enabled: bool
    next_run_at: str | None


class DashboardRunItem(BaseModel):
    id: str
    target_name: str | None
    scheduled_for: str | None
    status: str
    stage: str


class DashboardData(BaseModel):
    tasks: list[DashboardTaskItem]
    accounts: list[AccountItem]
    recent_runs: list[DashboardRunItem]
    platform_status: PlatformStatus


class AdminUserRow(UserInfo):
    status: str
    must_change_password: bool
    created_at: str | None
    quota: QuotaSummary


class QuotaPolicy(BaseModel):
    default_amount: int
    default_duration_days: int | None
    max_saved_tasks: int


class AdminUserQuotaResponse(BaseModel):
    user: AdminUserRow
    quota: QuotaSummary


class CreateAccountResponse(BaseModel):
    id: str
    display_name: str


class ListAccountsResponse(BaseModel):
    items: list[AccountItem]


class ListConversationsResponse(BaseModel):
    items: list[ConversationItem]


class ListTasksResponse(BaseModel):
    items: list[TaskItem]
    quota: QuotaSummary


class ListRunsResponse(BaseModel):
    items: list[RunItem]
    page: Pagination
    show_owner: bool


class ListUsersResponse(BaseModel):
    items: list[AdminUserRow]
    page: Pagination


class TemporaryPasswordResponse(BaseModel):
    temporary_password: str


class ScheduledTaskDetail(BaseModel):
    task_id: str
    cron_expr: str
    event_category: str
    params: dict | list | str | int | float | bool | None
    target_env: str
    enabled: bool
    status: str
    last_run_at: str | None
    next_run_at: str | None
    created_at: str | None
    updated_at: str | None


class AccountCookiesResponse(BaseModel):
    account_id: str
    cookie_version: int
    cookies_json: str


class WriteRunResponse(BaseModel):
    id: str


class BrowserAcquireResponse(BaseModel):
    sessionid: str | None
    ws_url: str | None
    headers: dict
    mode: str | None


# ---- 扫码登录 ----
class ScanStartBody(BaseModel):
    fingerprint: dict = {}


class ScanStartResponse(BaseModel):
    sessionid: str


class ScanQrResponse(BaseModel):
    status: str
    qr_base64: str | None = None


class ScanStatusResponse(BaseModel):
    status: str
    account: AccountItem | None = None
    avatar_base64: str | None = None


class ScanVerifyCodeBody(BaseModel):
    code: str


class ScanVerifyCodeResponse(BaseModel):
    status: str


class ScanResendStatusResponse(BaseModel):
    status: str
    seconds: int | None = None


class ScanResendCodeResponse(BaseModel):
    status: str
    seconds: int | None = None


class SystemConfigResponse(BaseModel):
    values: dict[str, str]
    secret_configured: dict[str, bool]
    installation_credentials_active: bool = False


class SystemConfigUpdateBody(BaseModel):
    values: dict[str, str]
    clear_secret_keys: list[str] = []
