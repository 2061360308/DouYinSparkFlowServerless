"""CloakBrowser keyless 容器: 浏览器启动 + WS 代理转发包。

镜像/服务版本以**仓库根目录的 `VERSION` 文件**为单一事实来源:
  - 构建镜像时 Dockerfile 用 ``--build-arg IMAGE_VERSION="$(cat VERSION)"`` 注入,
    并写成容器 ENV ``IMAGE_VERSION``;
  - 运行时本模块优先读该 ENV; 脱离容器(本地开发)则回退向上查找 `VERSION` 文件;
  - 都取不到时用 ``0.0.0-dev`` 兜底。
`GET /` 健康检查会把该版本放进 ``version`` 字段, 便于核对线上部署的镜像版本。
"""
from __future__ import annotations

import os
from pathlib import Path

_FALLBACK_VERSION = "0.0.0-dev"


def _resolve_version() -> str:
    env = os.environ.get("IMAGE_VERSION")
    if env and env.strip():
        return env.strip()
    # 本地(非容器)运行: 从本文件向上逐级查找仓库根的 VERSION 文件
    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        version_file = base / "VERSION"
        if version_file.is_file():
            try:
                text = version_file.read_text(encoding="utf-8").strip()
            except OSError:
                break
            if text:
                return text
            break
    return _FALLBACK_VERSION


__version__ = _resolve_version()
