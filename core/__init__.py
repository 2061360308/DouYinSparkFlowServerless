"""core：业务/领域层（从 server 抽出）。

职责：实现业务用例并编排各能力模块，被 server(API 层) 与 task(定时执行) 复用；
不依赖 FastAPI / HTTP，从而让定时任务执行路径(task.run / FC)无需拉起 web 层。

结构:
- services/            : 业务服务(accounts / tasks / task_capacity 额度 / users / auth / audit)
- handlers/            : 业务事件 handler(续火 等), 注册进 task.registry(供 task.run 回调)
- security.py crypto.py pii.py : 口令/会话/CSRF、cookie 与 PII 加密
- config.py rate_limit.py timeutil.py : 运行配置(密钥走环境变量)、DB 限流、UTC 工具
- cli.py (python -m core) : 管理命令(create-admin / set-password)

依赖方向: core → { db, browser, task(crud/dispatcher) }; 不反向依赖 server。
"""
