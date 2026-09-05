"""server：API 适配层（FastAPI）。

只负责 HTTP 边界与应用装配，不含业务逻辑（业务在 core/）：
- app.py    : 应用工厂 + lifespan(起停 Tortoise 常驻连接) + 异常映射
- deps.py   : 依赖注入(当前用户 / CSRF / 管理员守卫), 取用 core 的配置与服务
- index.py  : ASGI 入口(Vercel / uvicorn server.index:app)
- routers/  : 接口蓝图(薄 handler, 只做 IO/校验, 调 core)

依赖方向: server(routers) → core → { db, browser, task }。
"""
