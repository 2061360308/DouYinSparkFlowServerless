"""访问 FastAPI 内部接口 /api/internal/* 的客户端（带服务令牌）。

供续火任务执行侧（FC 事件函数 / 本地 core.task.run）统一取数与回写，不直连 DB。
环境变量：
- SPARK_API_BASE_URL   : FastAPI 基址（如 https://<app>.vercel.app 或 http://127.0.0.1:8000）
- SPARK_SERVICE_TOKEN  : 机器身份服务令牌（与后端 Settings.service_token 一致）
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class ApiClientError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class InternalApiClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or os.environ.get("SPARK_API_BASE_URL", "")).rstrip("/")
        self.token = token or os.environ.get("SPARK_SERVICE_TOKEN", "")
        self.timeout = timeout
        if not self.base_url:
            raise ApiClientError("SPARK_API_BASE_URL 未配置")
        if not self.token:
            raise ApiClientError("SPARK_SERVICE_TOKEN 未配置")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, json: Any = None) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(method, url, headers=self._headers(), json=json)
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:  # noqa: BLE001
                pass
            raise ApiClientError(f"{method} {path} -> {resp.status_code}: {detail}", resp.status_code)
        if resp.content:
            return resp.json()
        return None

    # ---- 计划任务(通用调度层) ----
    async def get_scheduled_task(self, task_id: str) -> dict:
        return await self._request("GET", f"/api/internal/scheduled-tasks/{task_id}")

    async def mark_started(self, task_id: str) -> None:
        await self._request("POST", f"/api/internal/scheduled-tasks/{task_id}/started")

    async def mark_result(self, task_id: str, ok: bool) -> None:
        await self._request("POST", f"/api/internal/scheduled-tasks/{task_id}/result", json={"ok": ok})

    # ---- 续火业务 ----
    async def get_spark_task(self, spark_task_id: str) -> dict:
        return await self._request("GET", f"/api/internal/spark-tasks/{spark_task_id}")

    async def get_account_cookies(self, account_id: str) -> dict:
        return await self._request("GET", f"/api/internal/accounts/{account_id}/cookies")

    async def acquire_browser(self, sessionid: str, fingerprint: dict | None = None) -> dict:
        return await self._request(
            "POST", "/api/internal/browser/acquire",
            json={"sessionid": sessionid, "fingerprint": fingerprint or {}},
        )

    async def write_run(
        self,
        spark_task_id: str,
        status: str,
        *,
        stage: str = "",
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> dict:
        return await self._request(
            "POST", f"/api/internal/spark-tasks/{spark_task_id}/runs",
            json={
                "status": status,
                "stage": stage,
                "error_code": error_code,
                "error_summary": error_summary,
            },
        )


def get_client() -> InternalApiClient:
    """构造默认客户端（从环境变量读取基址与令牌）。"""
    return InternalApiClient()
