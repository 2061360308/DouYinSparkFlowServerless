"""Vercel / ASGI 入口：暴露 ``app`` 供平台托管。

Vercel Python runtime 直接加载本模块的 ``app``；本地可用
``uvicorn api.index:app --reload`` 运行。
"""

from api.app import create_app

app = create_app()
