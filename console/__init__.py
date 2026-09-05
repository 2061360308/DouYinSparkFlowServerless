"""控制台后端（由 spark_console 迁移）：无状态、适配 serverless。

- 密钥从环境变量（base64）读取，不依赖本地文件；
- 持久化统一走 db/（Tortoise）；
- 邮件请求内联发送，无发件箱/无 worker/无 cron。
"""
