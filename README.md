# DouYinSpark Serverless

抖音「续火」自动化：控制台（Vue3 + FastAPI/Vercel）调度浏览器机器人（CloakBrowser 云函数持续运行，本地 Docker 可选），经阿里云 FC3 + EventBridge 定时续火。

```
panel/    前端 (Vue3 + Naive UI)
server/   FastAPI 后端入口 (Vercel serverless)
core/     核心库 (模型/任务调度/浏览器管理/云函数客户端)
aliyunFC/ FC3 云函数 + ROS 模板 + taskrunner 执行器镜像
.github/  GitHub Actions (ACR 镜像构建)
```

## 部署

### 1. 控制台（Vercel / 任意 Python 服务）

1. 安装 `requirements.txt`；前端 `cd panel && npm ci && npm run build`。
2. 配置持久化 `DATABASE_URL`（生产用 PostgreSQL）并初始化：`python -m core.db`。
3. 按下方「环境变量」配置固定密钥与服务令牌，关闭 `SPARK_DEV_INSECURE`。
4. 创建管理员、完成首次改密，进入安装向导录入阿里云 AK/SK 部署云资源。

### 2. 云资源（安装向导 / ROS 模板）

- 调用 ROS 创建资源栈（FC3 浏览器函数 + Web 触发器 + taskrunner 执行器 + EventBridge 定时链路），模板固定地域 `cn-hangzhou`、栈名 `DouyinSpark`。
- 镜像由 GitHub Actions 构建并推送 ACR（见 `.github/workflows/acr-build.yml`）。

### 3. 本地（Docker）模式

设置 `DouyinSparkDocker=1` 走本地浏览器模式，跳过云安装。

## 环境变量

### 必需（生产）

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | 数据库连接串；生产必须用持久化数据库（serverless 不能依赖临时 SQLite）。默认 `sqlite://db.sqlite3`。PostgreSQL 连接串写成 `postgres://...` 即可，应用会自动归一化为 psycopg 后端 |
| `SPARK_COOKIE_KEY_B64` | 固定 **32 字节** 的 Base64 密钥；加密抖音 cookie、登录输入、系统凭据、安装记录（AES-GCM）。更换会导致旧数据无法解密 |
| `SPARK_SESSION_KEY_B64` | 固定 **≥32 字节** 的 Base64 密钥；会话 token 派生 |
| `SPARK_SERVICE_TOKEN` | **≥32 字符** 的机器身份令牌；任务执行器访问 `/api/internal/*` 时校验 |
| `SPARK_PUBLIC_BASE_URL` | 控制台公开 **HTTPS** 地址；注入云函数模板 `ApiBaseUrl` |

### 首管理员引导（可选，serverless 推荐）

> 不配置则需用 CLI 离线创建：`python -m core create-admin <用户名> --password <密码>`

| 变量 | 说明 |
| --- | --- |
| `SPARK_ADMIN_USERNAME` | 自动创建的首个管理员用户名（3–32 位字母/数字/下划线/短横线） |
| `SPARK_ADMIN_PASSWORD` | 对应密码（≥10 位且含字母和数字）；登录后强制改密。数据库已有任何管理员时忽略 |

> `SPARK_DEV_INSECURE` 生产必须**不设置**。缺失上述密钥时后端会随机生成，且安装接口会被拒绝（`/api/install/status` 返回缺失项）。

### 邮件通知（可选）

| 变量 | 说明 |
| --- | --- |
| `SPARK_EMAIL_ENABLED` | `true` 时启用邮件通知 |
| `RESEND_API_KEY` / `RESEND_FROM` | Resend 发信凭据/发件人 |
| `SPARK_PII_KEY_B64` | 开邮件后必需的 **32 字节** Base64 密钥，加密邮箱等 PII |

### 云模式 / 任务调度（可选）

| 变量 | 说明 |
| --- | --- |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET`（或 `SPARK_ALIYUN_AK`/`SPARK_ALIYUN_SK`） | 阿里云凭据备用来源；安装成功后可省略，优先用安装记录中的 AK/SK |
| `SPARK_ALIYUN_REGION` | 默认 `cn-hangzhou` |
| `SPARK_EVENTBRIDGE_BUS` | 事件总线名，默认 `default` |
| `SPARK_EVENTBRIDGE_TZ` | 定时触发时区，默认 `GMT+08:00` |

### 本地运行（可选）

| 变量 | 说明 |
| --- | --- |
| `DouyinSparkDocker` | 置为任意非空值 → 本地 Docker 浏览器模式，跳过云安装 |
| `CLOAKBROWSER_BINARY_PATH` | 本地浏览器二进制路径 |
| `SPARK_SECURE_COOKIES` | 默认 `true`；本地 http 联调设 `false` |
| `SPARK_TIMEZONE` | 默认 `Asia/Shanghai`（每日任务 cron 基准） |
| `TASK_WINDOWS_PYTHON` / `TASK_WINDOWS_WORKDIR` | Windows 本地执行器所用 python/工作目录 |

> 非环境变量、通过管理界面录入并加密存储（`system_secrets` 表）：`platform_access_key_id`、`platform_access_key_secret`、`image_registry_password`。这些字段的 GET 接口永远返回空值，只有 `secret_configured` 标记。

> GitHub Actions 镜像构建还需在仓库 Settings → Secrets 配置 `ACR_USERNAME`、`ACR_PASSWORD`。

## 阿里云 AK 所需权限

安装向导录入的 AK/SK 承担以下操作：

1. **ROS 资源编排**：创建/查询/删除资源栈（栈内创建 RAM 角色、FC3 函数与触发器、EventBridge 事件总线/连接/API 目标/规则）；
2. **EventBridge 定时调度**：增删改任务的事件源（`Create/Update/DeleteEventSource`）；
3. **FC 云函数会话**：销毁浏览器会话（`fc:DeleteSession`）；
4. **STS `GetCallerIdentity`**：解析账号 ID（所有有效 AK 均可调用，无需额外授权）。

### 快速方案（系统策略）

为 RAM 用户或角色附加以下系统策略即可完整部署：

| 系统策略 | 用途 |
| --- | --- |
| `AliyunROSFullAccess` | 资源栈创建/管理 |
| `AliyunFCFullAccess` | FC3 函数、触发器、会话销毁 |
| `AliyunEventBridgeFullAccess` | 事件总线、规则、定时事件源 |
| `AliyunRAMFullAccess` | 模板自动创建 FC 服务角色并附加策略 |

### 最小化自定义策略

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ros:CreateStack", "ros:GetStack", "ros:DeleteStack",
        "ros:ListStackEvents", "ros:GetTemplate",
        "ram:CreateRole", "ram:GetRole", "ram:DeleteRole",
        "ram:AttachPolicyToRole", "ram:DetachPolicyFromRole",
        "ram:CreateServiceLinkedRole",
        "fc:CreateFunction", "fc:GetFunction", "fc:UpdateFunction", "fc:DeleteFunction",
        "fc:CreateTrigger", "fc:GetTrigger", "fc:DeleteTrigger", "fc:ListTriggers",
        "fc:DeleteSession",
        "eventbridge:CreateEventBus", "eventbridge:GetEventBus", "eventbridge:DeleteEventBus",
        "eventbridge:CreateConnection", "eventbridge:GetConnection", "eventbridge:DeleteConnection",
        "eventbridge:CreateApiDestination", "eventbridge:GetApiDestination", "eventbridge:DeleteApiDestination",
        "eventbridge:CreateRule", "eventbridge:UpdateRule", "eventbridge:DeleteRule", "eventbridge:GetRule",
        "eventbridge:CreateEventSource", "eventbridge:UpdateEventSource", "eventbridge:DeleteEventSource",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

> 权限边界：AK 只在安装与调度时使用。生产建议对 RAM 用户做最小授权、限制区域为 `cn-hangzhou`，并定期轮换密钥；安装完成后该凭据通常不再被普通业务读写。