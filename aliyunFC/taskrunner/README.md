# 续火任务执行器（taskrunner）

FC3 自定义容器「事件函数」，被 EventBridge 定时事件源经 API 端点(HTTP)触发后执行一次续火任务。

## 职责
- 从事件载荷取 `task_id` → 调 `core.task.run.run_task`。
- 统一经 FastAPI 内部接口 `/api/internal/*`（服务令牌鉴权）取计划任务/续火任务详情、
  解密 cookie、申请远程浏览器、回写执行状态与执行记录；**不直连数据库**。
- 浏览器在远端（cloakbrowser）：`playwright.connect_over_cdp(ws_url, headers)` 驱动，
  故本镜像**不含 chromium**，规格可很小。
- 触发链路：EventBridge 定时事件源 → 总线 → 规则(`acs.api.destination`) → Connection 注入
  `Authorization: Bearer <token>` → HTTP 触发器 → 本容器；容器按 `SPARK_INVOKE_BEARER` 校验 Bearer。

## 运行环境变量（部署时由 ROS 注入函数）
- `SPARK_API_BASE_URL`：FastAPI 基址（如 `https://<app>.vercel.app`）。
- `SPARK_SERVICE_TOKEN`：机器身份服务令牌（与后端一致）。
- `FC_SERVER_PORT`：容器 HTTP 端口（默认 9000，与 `CustomContainerConfig.Port` 一致）。

> 鉴权由 FC HTTP 触发器（`authType=function` + Bearer tokens）完成，**容器内不再校验 Bearer**。

## 构建（上下文 = 仓库根，需带上 `core/`）
```bash
docker build -f aliyunFC/taskrunner/Dockerfile -t <acr>/douyin_spark_runner:$(cat aliyunFC/taskrunner/VERSION) .
```
CI 见 `.cnb.yml` 的 `taskrunner` 流水线（改动 `aliyunFC/taskrunner/**` 或 `core/**` 时构建推送 ACR）。

## 本地调试
```bash
SPARK_API_BASE_URL=http://127.0.0.1:8000 SPARK_SERVICE_TOKEN=xxx \
  python aliyunFC/taskrunner/invoke_server.py
curl -XPOST localhost:9000/invoke -d '{"data":{"task_id":"<id>"}}'
```
