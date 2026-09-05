# 开发说明

面向**维护者/二次开发者**：各模块职责、关键实现与设计不变式。整体是"单实例单
浏览器 + 会话亲和 + 懒启动"的精简 CDP 代理。

## 架构与数据流

```
外部客户端 (Playwright / 裸 ws / curl)
   │  HTTPS/WSS, 头: sessionID (+X-Browser-Cfg)
   ▼
FC 网关 —— HeaderField 亲和(键 sessionid) —— 同会话稳定路由到同实例
   ▼
┌───────────────────── 容器 (PID1 = supervisor) ──────────────────────┐
│  app/ws_proxy   0.0.0.0:9000   HTTP + WS 同端口                       │
│      │ /start → gate.ensure()   业务端点/WS → 转发                    │
│      ▼                                                               │
│  app/browser    BrowserManager(gate) —— 懒启动/复用/切换             │
│      │ subprocess.Popen                                              │
│      ▼                                                               │
│  stealth Chromium   127.0.0.1:9222 (remote debugging, 仅本机可达)    │
└──────────────────────────────────────────────────────────────────────┘
```

三条主线：
1. **控制面**：`GET /start` → `gate.ensure()` 决定启动/复用/切换浏览器。
2. **数据面**：`/json/*` 与 WS 由代理转发到本机 9222；WS 双向 pump。
3. **守护面**：supervisor watchdog 监视进程崩溃并按原配置重启。

## 模块职责

### `entrypoint.sh` — 容器入口

- 默认 `BROWSER_HEADLESS=true`：直接 `exec python -m app.supervisor`，无需显示环境。
- `false` 时才拉起 `Xvfb :99` + `openbox`（需构建期 `ENABLE_HEADED=true` 预装），
  并轮询等待 X server 就绪而非盲等。
- 清理上次残留的 X 锁（`/tmp/.X99-lock` 等），防 docker restart 后启动失败。

### `app/supervisor.py` — 容器编排器（PID 1）

- **懒启动时序**：先 `asyncio.create_task(serve_proxy(...))` 让 WS 代理监听 9000
  （`GET /` 立即 200，FC 判定实例启动成功），浏览器不预启动。
- **watchdog**（`_browser_watchdog`）：每 2s 检查 `gate.browser.process.poll()`；
  已创建的浏览器崩溃则 `await gate.restart_current()` 按原 cfg 重启。从未 `/start`
  时空转；重启失败由 gate 清空引用，交给下次 `/start` 重建，避免按过期配置空转。
- **优雅停机**：`SIGTERM/SIGINT` 置 `stop` 事件 → 取消 serve/watchdog → `gate.stop()`
  终止浏览器。
- 读取环境变量（`CDP_PORT`/`PROXY_PORT`/`BROWSER_HEADLESS`/`BROWSER_READY_TIMEOUT`）
  构造 `BrowserManager`。`env_int`/`env_float` 复用自 `ws_proxy`（不重复实现）。

### `app/browser.py` — 浏览器进程管理 + 会话门（gate）

**`StealthBrowser`**：单个 Chromium 实例的生命周期。

- `_stealth_args()`：原生生成上游默认 stealth 集
  `--no-sandbox --fingerprint=<seed> --fingerprint-platform=windows`，
  条件追加 `--fingerprint-timezone/-locale`、`--lang`、`--proxy-server`、
  headed 下 `--start-maximized`。
- `start()`：幂等（进程在跑直接返回）；`mkdir` profile 后调
  `_clear_singleton_locks()` 清理崩溃残留的 `SingletonLock/Socket/Cookie`
  （沿用同一 `--user-data-dir` 重启时偶发"profile 正被使用"），再
  `Popen([binary, *base, *stealth, *cdp_flags, *extra_args])`。CDP 仅绑
  `127.0.0.1`。
- `wait_ready()`：轮询 `http://127.0.0.1:9222/json/version`，指数退避；进程提前
  退出立即抛错（提示查看 stderr 定位缺库）。
- `stop()`：`terminate → wait(timeout) → kill` 优雅停止；随机指纹的**临时 profile**
  退出时 `rmtree` 清理。
- profile 策略：有 `seed` → 持久化目录（`PROFILE_DIR`，可挂 NAS）；无 `seed` →
  `tempfile.mkdtemp` 随机身份，退出即删。

**`normalize_cfg(raw)`**：把客户端 JSON 规范化为稳定 dict（None/空串归一、
`extra_args` 排序）。安全加固：`_is_blocked_arg` 过滤 `--remote-debugging-*` /
`--user-data-dir`（防客户端覆盖 CDP 绑定或 profile 目录、绕过会话隔离）。

**`BrowserManager`（gate）**：单实例内的浏览器门，`asyncio.Lock` 串行化。核心
状态机 `ensure(session_id, cfg_raw, active_ws)`：

| 当前状态 | 请求 | 动作 |
| --- | --- | --- |
| 运行中 & 同 `sessionID` | 复用 | 直接命中（同会话重连） |
| 运行中 & 不同 `sessionID` & 有活跃 WS | 拒绝 | 抛 `BrowserBusy` → 409（不踢人） |
| 运行中 & 不同 `sessionID` & 空闲 | 切换 | `stop` 旧 → 按新 cfg 启新 |
| 无进程 / 旧进程已崩溃残留 | 新建 | 残留对象先 `stop` 清理（防临时 profile 泄漏）再启新 |

- `chrome_exists()` / `current_session_id`：不加锁的只读快照，供代理层快速失败/
  防串台判断。
- `restart_current()`：watchdog 用，按 `self._cfg` 原配置重启；失败清空引用。
- `short_sid()`：日志用截断（`sessionID` 是可路由能力凭据，不整串落日志）。

### `app/ws_proxy.py` — HTTP/WS 代理（唯一监听入口）

`websockets.serve` 单端口同时处理 HTTP 与 WS 升级。

- **`_process_request`**（HTTP 回调，返回 `Response` 即终止握手，返回 `None` 进入
  WS handler）：
  - `GET /` → `_health_payload`，恒 200（不等待浏览器）。
  - `GET /start` → `_handle_start`：解析两头 → `gate.ensure()` → 返回稳定 ws。
  - 业务端点/WS：`gate` 存在但浏览器未创建 → 503 快速失败（不空等）；
    请求 `sessionID` ≠ 本实例会话 → 409 防串台；否则 `_wait_browser_ready`
    自动等待就绪（崩溃重启期间客户端无感）后放行。
  - `/json/version`、`/json/list` 转发并**重写** `webSocketDebuggerUrl`。
- **稳定 ws 根地址**（`_stable_browser_ws`）：返回 `ws(s)://<host>/`，不含随机
  uuid。根路径 WS 到达时 `route_ws` 才现查后端真实 `webSocketDebuggerUrl`，
  从而与"具体实例/进程"解耦——FC 扩容换实例或崩溃重启后地址依旧有效，消除
  "先取地址后连接落在不同实例"的 uuid 失配。
- **WS 转发**（`_relay` + `_pump`）：客户端 ws ↔ 后端 ws 双向泵送；连后端前轻量
  重试（浏览器重启窗口）；后端关闭则以 1011 关客户端促其重连。`max_size` 放宽到
  64MB（CDP DOM snapshot 等大消息）。
- **Origin 防护**（`_origin_allowed`）：无 Origin（纯脚本/CDP 客户端）放行；仅对
  loopback 保留 devtools 白名单，公网端口不做 Origin 白名单（外部客户端直连）。
- **大小写不敏感取头**（`_header_value`）：FC 网关可能改写 header 名大小写。
- **稳定/超时**：`_wait_browser_ready` 轮询后端就绪，超时（`WAIT_BROWSER_TIMEOUT`）
  返回 5xx；`active_ws` 计数供 `/start` 判断能否切换浏览器。

### 客户端脚本

- **[demo/connect_demo.py](../demo/connect_demo.py)**：纯 URL（无 AK）直连 +
  `cloakbrowser` 人类操作模拟的完整示例，见 [usage.md](usage.md)。
- **[../test_fc_browser.py](../test_fc_browser.py)**：部署冒烟测试——`/start` 懒
  启动后 `connect_over_cdp` 打开抖音、截图，最小化验证一次链路是否打通（无 AK）。

> 会话的主动管理（`ListSessions` 存活查询 / `DeleteSession` 立即停实例）由 FC
> OpenAPI 提供、需 AK/SK；**直连驱动用不到**，故本仓库不内置其封装，需要时直接
> 调 FC SDK 即可。

### `Dockerfile` — 镜像构建

1. 系统运行库：Chromium 最小依赖集 + `fonts-liberation`（**无 CJK 字体**：抖音等
   中文站截图会是豆腐块，需要时加 `fonts-noto-cjk`，权衡体积）。
2. 下载 stealth Chromium：`CLOAK_DOWNLOAD_URL → 加速镜像 → 官方直链` 依次 fallback，
   `sha256sum -c` 校验；整目录平铺拷到 `/opt/cloakbrowser/`（Chromium 非自包含，
   缺 `icudtl.dat` 会 SIGTRAP），校验 `icudtl.dat` 存在。
3. 唯一第三方 Python 依赖 `websockets==17.1`。
4. `ENTRYPOINT ["/entrypoint.sh"]`，`EXPOSE 9000`。

### 版本管理

镜像版本以**仓库根目录的 `VERSION` 文件**为单一事实来源：

- 构建：`docker build --build-arg IMAGE_VERSION="$(cat VERSION)" ...`，写入镜像
  OCI label `org.opencontainers.image.version` 与容器 ENV `IMAGE_VERSION`。
- 运行：`app/__init__.py` 的 `__version__` 优先读 ENV `IMAGE_VERSION`，脱离容器
  （本地）则向上查找 `VERSION` 文件，兜底 `0.0.0-dev`。
- 观测：`GET /` 健康检查返回 `version` 字段，可核对线上实际部署的镜像版本。
- 发版：改 `VERSION` 一处即可（勿在 `Dockerfile`/`__init__.py` 里另写死版本号）。

## 设计不变式（改动务必保持）

- **单实例并发 = 1、单实例单浏览器**：`ensure` 的切换/占用语义、`active_ws` 判断
  都建立在此之上。
- **`GET /` 永远不阻塞、恒 200**：FC 探活与崩溃重启期间实例存活全靠它；健康检查
  勿改用 `/json/version`（懒启动未 `/start` 时它返回 503，会被误判 unhealthy）。
- **对外只暴露稳定根 ws**：任何"把带 uuid 的具体地址透给客户端"的改动都会在扩容/
  重启时炸连接。
- **指纹参数只走 `X-Browser-Cfg`**：不要重新引入 `FINGERPRINT_SEED` 等环境变量注入。
- **`sessionID` 视为凭据**：日志用 `short_sid` 截断。

## 本地开发

```bash
docker compose up -d --build      # 构建并起容器(healthcheck 用 GET /)
docker logs -f cloakbrowser

# 纯逻辑单测(browser.py 仅依赖标准库, 可离线跑):
python -c "from app.browser import normalize_cfg, short_sid; print(normalize_cfg({'seed':1,'extra_args':['--user-data-dir=/x','--lang=zh']}))"
```

代理/编排（`ws_proxy`、`supervisor`）依赖 `websockets`；无该依赖时可用
`python -m py_compile app/*.py` 做语法校验。

## 已知可改进项（待办）

- 客户端无鉴权：`/start` 与 WS 依赖 FC 触发器自身鉴权，可加可选 `PROXY_TOKEN`。
- 根路径 WS 每次现查 `/json/version`，可按实例缓存 `webSocketDebuggerUrl`。
- 缺纯逻辑单测框架（`normalize_cfg`/`build_session_id`/头解析均可离线测）。
- 中文站截图需 `fonts-noto-cjk`（默认未装，权衡镜像体积）。
