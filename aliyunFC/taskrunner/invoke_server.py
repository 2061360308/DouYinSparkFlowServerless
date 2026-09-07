"""FC3 自定义容器「事件函数」invoke server。

FC 通过 HTTP 调用容器执行事件函数：本服务监听 0.0.0.0:$FC_SERVER_PORT，
``POST /invoke``（或任意 POST）请求体为事件载荷；从中取 ``task_id`` 后调用
``core.task.run.run_task``，返回执行结果 JSON。``GET`` 用于健康探测。

事件载荷（EventBridge → FC 目标）里 task_id 可能在顶层或 ``data`` 内（data 可能是
JSON 字符串），这里做兼容解析。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.task.run import run_task

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("taskrunner")


def _extract_task_id(raw: str) -> str | None:
    try:
        evt = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(evt, dict):
        return None
    if evt.get("task_id"):
        return str(evt["task_id"])
    data = evt.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    if isinstance(data, dict) and data.get("task_id"):
        return str(data["task_id"])
    if isinstance(data, dict):
        user_data = data.get('UserData')
        if isinstance(user_data, str):
            try:
                user_data = json.loads(user_data)
            except json.JSONDecodeError:
                return None
        if isinstance(user_data, dict) and user_data.get('task_id'):
            return str(user_data['task_id'])
    return None


def _extract_scheduled_for(raw: str) -> str | None:
    """Preserve the original CloudEvent time across delivery retries."""
    event = json.loads(raw)
    value = event.get('time') if isinstance(event, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError('invalid event time')
    return value


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802  健康探测
        self._send(200, {"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        # 鉴权由 FC HTTP 触发器(authType=function + Bearer tokens)完成, 容器内不再校验。
        length = int(self.headers.get("content-length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        task_id = _extract_task_id(raw)
        if not task_id:
            self._send(400, {"ok": False, "msg": "事件载荷缺少 task_id"})
            return
        try:
            scheduled_for = _extract_scheduled_for(raw)
        except ValueError:
            self._send(400, {'ok': False, 'msg': '事件必须携带原始计划时间 time'})
            return
        try:
            resp = asyncio.run(run_task(task_id, scheduled_for))
        except Exception as error:  # noqa: BLE001
            logger.exception("run_task 异常 task_id=%s", task_id)
            self._send(500, {"ok": False, "msg": str(error)})
            return
        self._send(200 if resp.get("ok") or resp.get('retryable') is False else 500, resp)

    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # 静默默认访问日志
        pass


def main() -> None:
    port = int(os.environ.get("FC_SERVER_PORT", "9000"))
    logger.info("taskrunner invoke server listening on 0.0.0.0:%s", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
