"""browser：浏览器实例管理模块。

- ``BrowserManager``：唯一入口（单例）。按部署环境自动选择后端并统一
  ``acquire`` / ``get`` / ``destroy``：
    - 设置环境变量 ``DouyinSparkDocker`` → 本地模式（服务器 docker，持久化管理
      chrome 进程 + 超时回收）；
    - 未设置（Vercel 等 Serverless）→ 云函数模式（对接 cloakbrowser-serverless，
      无状态，签名调用函数 URL + FC DeleteSession）。
- ``local``：本地以独立进程方式启动/停止 CloakBrowser，返回 pid 与 CDP ws 地址；
  并提供按 sessionid 组织的 ``LocalBackend``。
- ``signer``：FC HTTP 触发器（authType=function）请求签名工具。
"""

from .local import (
    OK,
    BrowserError,
    LocalBackend,
    find_binary,
    is_alive,
    launch,
    launch_async,
    stop,
    stop_async,
)
from .manager import BrowserManager, is_docker_deployment

__all__ = [
    "BrowserManager",
    "is_docker_deployment",
    "LocalBackend",
    "OK",
    "BrowserError",
    "find_binary",
    "launch",
    "launch_async",
    "stop",
    "stop_async",
    "is_alive",
]
