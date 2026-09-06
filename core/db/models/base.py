"""模型层公共工具。

所有 Tortoise 模型共享的 ``uuid_string()`` 生成器放在此处，避免多文件重复定义。
"""

from __future__ import annotations

import uuid


def uuid_string() -> str:
    """返回标准 UUID4 字符串，作为各表主键默认值。"""
    return str(uuid.uuid4())
