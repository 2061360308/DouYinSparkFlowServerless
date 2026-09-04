"""browser：浏览器实例管理模块。

- ``local``：在本地以独立进程方式启动/停止 CloakBrowser，返回 pid 与
  CDP 调试 ws 地址（支持指纹 seed、地区、代理、伪装 Windows 等）。
"""

from .local import (
    OK,
    BrowserError,
    find_binary,
    is_alive,
    launch,
    launch_async,
    stop,
    stop_async,
)

__all__ = [
    "OK",
    "BrowserError",
    "find_binary",
    "launch",
    "launch_async",
    "stop",
    "stop_async",
    "is_alive",
]
