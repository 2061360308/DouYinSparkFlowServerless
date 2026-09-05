# cloakbrowser-serverless

为适配阿里云函数计算（FC）等 Serverless 无头环境，基于开源
[CloakHQ/CloakBrowser](https://github.com/CloakHQ/CloakBrowser) 自建的
**stealth Chromium** Docker 镜像。

相比官方 `cloakserve` 常驻服务，自建镜像更**灵活自由**：浏览器按需懒启动、
指纹参数按请求下发、单实例单浏览器按会话隔离、用完即销毁，天然契合 Serverless
的按量弹性，也不必绑定官方 wrapper 的一堆运行时依赖。底层是**源码级补丁**的
stealth Chromium：Linux 上一律伪装成 **Windows** 环境，配合固定 `seed` 得到
**稳定一致的指纹**（表现得像"返回访客"而非每次都换新设备），从 canvas / WebGL /
音频 / 字体 / GPU 到 UA、自动化信号全部在二进制层伪装，比 JS 注入类方案更难被
反爬检测与风控识别。

> 详细协议、端点、客户端接入见 **[docs/usage.md](docs/usage.md)**；
> 各模块实现细节见 **[docs/development.md](docs/development.md)**；
> 可直接运行的最小示例见 **[demo/](demo/)**。

## 特性

- **懒启动**：容器启动只监听端口、探活秒过；浏览器等首个 `GET /start` 按需
  创建，不预热、不空耗资源。
- **会话亲和 + 多用户隔离**：同一会话的请求稳定路由到同一实例，不同会话各自
  独立浏览器，互不串扰。
- **零 wrapper / 轻量镜像**：不引入 CloakBrowser 的 Python wrapper，stealth 参数
  原生生成；第三方 Python 依赖仅 `websockets` 一个。
- **keyless stealth Chromium v146**：构建期从 CloakHQ 官方 GitHub Release 下载
  并做 sha256 校验，预置进镜像层（运行时不再联网）。
- **默认 headless**：无需 Xvfb/显示环境，天然适配 FC 等无头平台
  （`BROWSER_HEADLESS=false` 需 `--build-arg ENABLE_HEADED=true` 构建）。
- **两个自定义头解耦身份与配置**：`sessionID`（FC 亲和会话 ID，1–64 字符）
  + `X-Browser-Cfg`（base64url JSON 配置），绕开 FC 亲和键的字符集/长度硬限制。
- **稳定 WS 根地址**：`/json/version` 与 `/start` 返回不含随机 uuid 的根路径
  地址，代理动态解析当前浏览器，跨实例扩容/崩溃重启后依旧有效。
- **健壮**：WS 断开后浏览器保留复用；进程崩溃自动按原配置重启；容器优雅停机
  （`SIGTERM`）清理浏览器。

## 构建与推送（ACR）

镜像内置 Chromium（约 200MB+），建议推送到与 FC 函数**同地域**的 ACR
（容器镜像服务，个人版即可），减少冷启动拉取时间。

```bash
# 镜像版本以仓库根目录的 VERSION 文件为准
VER=$(cat VERSION)

# 1) 构建(注入镜像版本; 默认 headless; 固定 chromium-v146 + sha256 校验, 构建期预下载)
docker build --build-arg IMAGE_VERSION="$VER" -t cloakbrowser-ws-proxy:"$VER" .

# 2) 打标签并推送到 ACR: registry.<region>.aliyuncs.com/<命名空间>/<镜像名>
IMG=registry.cn-hangzhou.aliyuncs.com/<namespace>/cloakbrowser
docker tag cloakbrowser-ws-proxy:"$VER" "$IMG:$VER"
docker tag cloakbrowser-ws-proxy:"$VER" "$IMG:latest"
docker login --username=<阿里云账号全名> registry.cn-hangzhou.aliyuncs.com
docker push "$IMG:$VER"
docker push "$IMG:latest"
```

常用可覆盖构建参数（国内构建节点友好，默认已走 DaoCloud 基镜像 / 阿里云 pip /
中科大 apt / GitHub 加速镜像）：

| 构建参数 | 说明 |
| --- | --- |
| `IMAGE_VERSION` | 镜像版本，建议传 `$(cat VERSION)`；写入 OCI label 与 `GET /` 的 `version` 字段 |
| `CLOAK_CHROMIUM_VERSION` | 浏览器版本（默认 `146.0.7680.177.5`） |
| `CLOAK_BINARY_SHA256` | 对应 asset 的 sha256 下载校验（勿改错） |
| `CLOAK_DOWNLOAD_URL` | 自建 OSS/内网完整下载 URL（最优先） |
| `CLOAK_DOWNLOAD_MIRRORS` | GitHub 加速镜像前缀列表（空格分隔，依次 fallback） |
| `ENABLE_HEADED` | `true` 时多装 Xvfb/openbox（headed 可视化） |
| `PIP_INDEX_URL` / `APT_MIRROR` | pip / apt 镜像源 |

> 若在 ACR/CI 构建节点直连 github.com 下载大文件很慢，请把
> `CLOAK_DOWNLOAD_MIRRORS` 换成可达的加速源，或用 `CLOAK_DOWNLOAD_URL` 指向
> 自建镜像。本地联调可直接 `docker compose up -d --build`。

## 云函数配置要点

创建 FC 函数（**自定义容器 Custom Container**），关键项：

1. **镜像**：选上一步 ACR 地址；启动命令/参数留空（用镜像 ENTRYPOINT）。
2. **端口 `9000`**；**健康检查路径 `/`**（懒启动下代理即刻就绪，探测秒过）。
3. **请求处理超时** ≥ 120s，覆盖 `/start` 冷启动（就绪上限默认 90s，可用
   `BROWSER_READY_TIMEOUT` 调整）。
4. **单实例并发数 = 1**：保证一个实例同一时刻只服务一个会话。
5. **开启会话亲和（关键）**：选 **HeaderField 亲和**，自定义键名填
   **`sessionid`**（值即客户端 `sessionID` 头，平台要求 1–64 字符、
   `^[A-Za-z0-9_][A-Za-z0-9_-]*$`，64 位 sha256 hex 恰好满足）。**未开启亲和**
   会导致 `/json/version` 与 WS 被路由到不同实例、连接失败。
6. 记录**公网入口**（形如 `https://<xxx>.cn-<region>.fcapp.run`）供客户端直连。

环境变量（均可选）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PROXY_PORT` | `9000` | 对外监听端口（FC 要求 9000，勿改） |
| `CDP_PORT` | `9222` | 浏览器内部 remote debugging 端口（仅 127.0.0.1） |
| `BROWSER_HEADLESS` | `true` | `false` 需 `ENABLE_HEADED=true` 构建 |
| `BROWSER_READY_TIMEOUT` | `90` | `/start` 冷启动就绪上限（秒），需 < FC 请求超时 |
| `WAIT_BROWSER_TIMEOUT` | `180` | 崩溃重启期间业务端点自动等待上限（秒） |
| `PROFILE_DIR` | `/data/profile` | 固定 seed 会话的 profile 目录（可挂 NAS 持久化） |
| `LOG_LEVEL` | `INFO` | 日志级别 |

> 浏览器指纹参数（seed/时区/语言/代理等）**不在环境变量里**，一律由客户端
> `X-Browser-Cfg` 头按请求下发（见 [docs/usage.md](docs/usage.md)）。

## 计费与持久化

- **计费回收**：需要立即停实例用 FC `DeleteSession`；不销毁时 WS 断开后浏览器
  保留复用，按量实例由 FC 空闲回收兜底。长期驻留可配固定（预留）实例。
- **持久化**：FC 只有 `/tmp` 保证可写；需保存登录态时把 NAS 挂到 `/data` 并设
  `PROFILE_DIR=/data/profile`（配固定 `seed` 才有意义）。
- **资源规格**：建议内存 ≥ 1 GB（Chromium 常驻约 400~800MB）。

## 许可与来源

本仓库独立实现"单实例单浏览器 + 会话亲和"的精简代理，未直接使用官方
`cloakserve`。stealth 参数与免费版 Chromium 二进制取自 CloakBrowser 上游
（MIT 开源、GitHub Release 分发），不引入其 Python wrapper 的任何运行时依赖。
