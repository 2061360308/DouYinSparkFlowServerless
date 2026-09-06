# DouyinSpark cloakbrowser-serverless

基于 ACR 自定义容器镜像, 一次性创建全部资源并部署 **FC3** 云函数(cloakbrowser stealth Chromium + websockets 代理 + 续火任务执行器), 支持 HEADER_FIELD 会话亲和, 函数通过默认网卡访问公网。

部署方式: **ROS 原生模板** — 单文件 YAML, 直接在阿里云 ROS 面板粘贴部署, 原生支持会话亲和。

## 目录结构

```
install
├── ros-template.yaml     # ROS 原生单文件模板(主交付, 可粘 ROS 面板)
├── ros_client.py         # ROS OpenAPI 客户端库(供后端模块调用创建/查询/取地址)
├── __init__.py           # 包声明, 支持 from install.ros_client import RosStackClient
├── readme.md
└── version.md
```

## 一键部署 (ROS 面板)

不需要本地安装任何工具, 直接在阿里云控制台粘贴 `ros-template.yaml` 部署:

1. 打开 [资源编排 ROS 控制台](https://ros.console.aliyun.com/) → **创建资源栈** → **使用现有模板** → **模板录入方式 = 输入模板** → **模板内容类型 = YAML**, 粘贴 `install/ros-template.yaml` 内容 → 下一步。
2. 在 **配置参数** 页填写模板参数(默认值可直接使用): 地域建议 `cn-hangzhou`(默认镜像所在区域)。**新建资源栈时输入栈名 `DouyinSpark`**(栈名是创建栈时的入参, 不写在模板里)。
3. 点击 **创建** 等待资源栈创建完成(约 1~3 分钟)。
4. 在 **资源栈 → 输出** 中查看: Web 触发器公网地址(`TriggerUrlInternet`)、续火任务执行器触发器地址(`TaskTriggerUrlInternet`)等。

> 注意事项:
> - 部署前请确认账号已完成 **实名认证** 并开通函数计算 FC、访问控制 RAM、事件总线 EventBridge 相关服务。
> - 会话亲和已内置(`SessionAffinity: HEADER_FIELD`), 无需额外传参, 客户端请求携带 `sessionid` 请求头即可享受亲和路由。
> - 会话函数强制 `instanceConcurrency=200`(已内置), 单实例实际并发由 `SessionConcurrencyPerInstance=1` 控制, 不影响资源占用。
> - 已开启"允许函数默认网卡访问公网"(`InternetAccess: true`), 函数可直接访问公网, 但出网 IP 不固定。
> - `Command`/`Entrypoint` 不填写(CustomContainerConfig 仅 Image/Port/HealthCheckConfig), 使用镜像内置启动命令。
> - 删除资源栈即可一键销毁全部资源(勾选删除保护会保留, 请按提示操作)。

## 在线 Vue 生成器对接

`ros-template.yaml` 即最终单文件模板, 在线 Vue 程序只需:

1. 读取 `install/ros-template.yaml` 内容。
2. 按用户收集的输入(函数名/镜像地址/函数规格/任务执行器规格/亲和参数/后端 API 地址等)替换 `Parameters` 中对应字段的 `Default` 值。
3. 输出渲染后的 YAML 字符串供用户在 ROS 面板粘贴部署(或调用 ROS API 直接创建资源栈)。

无需拼接多个文件 — 模板是一个完整自包含的 YAML。资源栈名称(`StackName`)是 `CreateStack` 的入参, 不作为模板字段, 建议 Vue 端单独收集(默认 `DouyinSpark`)。

## ROS 客户端库(后端模块调用)

`install/ros_client.py` 是对 ROS OpenAPI (2019-09-10) 的封装, 提供**五个核心同步方法**供后端其他模块直接调用, 无需安装 CLI:

| 方法 | 能力 |
|---|---|
| `create_stack(template_body, stack_name, parameters=...)` | ① 发起创建, 同步返回 `stack_id`(后台异步创建) |
| `get_stack_status(stack_id)` | ② 单次查询资源栈信息(Status / StatusReason / Outputs / Parameters 等) |
| `wait_stack_complete(stack_id, interval=, timeout=)` | ② 轮询直到终态; 成功返回最终信息, 失败抛 `StackFailedError`(自动携带失败资源原因), 超时抛 `StackWaitTimeoutError` |
| `get_stack_outputs(stack_id)` | ③ 取全部输出 `{OutputKey: OutputValue}`(`TriggerUrlInternet` / `TaskTriggerUrlInternet` / `FunctionName` 等) |
| `get_trigger_url(stack_id)` | ③ 便利方法: 直接取 Web 触发器公网访问地址(`Outputs.TriggerUrlInternet`) |

安装依赖:

```bash
pip install alibabacloud_ros20190910
```

支持 STS 临时凭证: `RosStackClient` 构造时传 `security_token`, 可免在后端前置长期 AK/SK。

调用示例(把 `aliyunFC` 父目录加入 PYTHONPATH):

```python
import sys
sys.path.insert(0, "/workspace/aliyunFC")

from install import RosStackClient  # 或 from install.ros_client import RosStackClient

client = RosStackClient(
    region="cn-hangzhou",
    access_key_id="LTAI...",          # 或后端配置中的 AK/SK
    access_key_secret="...",
)

# ① 创建资源栈(返回 stack_id, 不等待创建完成)
stack_id = client.create_stack(
    template_body=open("install/ros-template.yaml", encoding="utf-8").read(),
    stack_name="DouyinSpark",          # 覆盖的参数只传此处, 其余走模板 Default
    parameters={"Cpu": "1", "MemorySize": "1536"},
)

# ② 轮询创建状态(成功返回, 失败抛异常并带失败原因)
client.wait_stack_complete(stack_id)

# ③ 取触发器公网访问地址
url = client.get_trigger_url(stack_id)  # -> https://<fn>-<uid>.cn-hangzhou.fcapp.run
```

### 常用异常

| 异常 | 触发场景 |
|---|---|
| `RosStackError` | ROS API 调用失败(鉴权 / 参数 / 网络等), 带 `code` / `request_id` / `details` |
| `StackFailedError` | 资源栈创建失败 / 回滚, `failed_events` 携带失败资源列表 |
| `StackWaitTimeoutError` | `wait_stack_complete` 超过 `timeout` 上限 |

`install/__init__.py` 已导出全部类型: `RosStackClient` / `RosStackError` / `StackFailedError` / `StackWaitTimeoutError`。

要点:
- 方法均为**同步**实现(与 `fc/fc_client.py` 同风格); 异步后端可用 `asyncio.to_thread` 包裹。
- `create_stack` 只传需覆盖的 `parameters`, 未指定参数自动沿模板 `Default`, 与 ROS 面板行为一致; 自动生成 `client_token` 保证幂等。
- `wait_stack_complete` 默认每 5s 轮询(`interval`)、最长 20 分钟(`timeout`); 创建失败自动拉 `ListStackEvents`, 把 `LogicalResourceId` / `ResourceType` / `StatusReason` 写入 `StackFailedError.failed_events`。
- 完整 outputs 用 `get_stack_outputs(stack_id)` 获取(`TriggerUrlInternet` / `TaskTriggerUrlInternet` / `FunctionName` / `TaskFunctionName` 等)。

## 默认资源规格

| 资源 | 规格 |
|---|---|
| 浏览器函数 | `DYSparkCloakBrowser`, 1 vCPU / 1536 MB 内存 / 10240 MB 磁盘 |
| 浏览器容器 | `crpi-yagm0mg4gyj902wq.cn-hangzhou.personal.cr.aliyuncs.com/oilu/cloakbrowser-serverless:latest`, 端口 9000, 镜像默认启动命令 |
| 任务执行器函数 | `DYSparkTaskRunner`, 0.5 vCPU / 512 MB 内存 / 512 MB 磁盘 |
| 任务执行器容器 | `crpi-yagm0mg4gyj902wq.cn-hangzhou.personal.cr.aliyuncs.com/oilu/douyin_spark_runner:latest`, 端口 9000 |
| 会话亲和 | HEADER_FIELD, 键名 `sessionid`, TTL 600s, 空闲 30s, 单实例会话并发 1 |
| 函数超时 | 浏览器 600s / 任务执行器 300s |
| 并发 | 实例并发 200(会话亲和强制值) / 会话并发 1, 无常驻实例 |
| 触发器 | Web(HTTP) 触发器, 默认 `anonymous`, 方法 GET/POST/PUT/DELETE/HEAD |
| 公网访问 | 默认网卡访问公网(`InternetAccess: true`), 不创建 VPC/NAT/EIP, 出网 IP 不固定 |
| 定时调度 | EventBridge 自定义事件总线 + Connection(Bearer 鉴权) + API 端点 + Rule, 触发任务执行器 |
| 名称前缀 | `DouyinSpark`(RAM 角色 / EventBridge 资源等名称前缀) |

## 模板参数说明(ROS Parameters)

| 参数 | 默认 | 说明 |
|---|---|---|
| NamePrefix | DouyinSpark | 资源名称前缀(RAM 角色 / EventBridge 资源等) |
| FunctionName | DYSparkCloakBrowser | 浏览器函数名称 |
| ImageUrl | ACR 镜像 | 浏览器容器镜像地址 |
| Cpu / MemorySize / DiskSize | 1 / 1536 / 10240 | 浏览器函数规格(CPU/MB内存/MB磁盘) |
| FunctionTimeout | 600 | 浏览器容器最大执行时间(秒) |
| ContainerPort | 9000 | 浏览器容器监听端口 |
| TriggerName / TriggerAuthType | webTrigger / anonymous | 浏览器触发器名称 / 鉴权方式 |
| SessionAffinityHeaderFieldName | sessionid | 亲和请求头名 |
| SessionTTLSeconds / SessionIdleTimeoutSeconds | 600 / 30 | 会话生命周期 / 空闲等待(秒) |
| SessionConcurrencyPerInstance | 1 | 单实例最大 Session 数 |
| DisableSessionIdReuse | false | Session 过期后拒绝复用 |
| HealthCheckUrl / 健康检查 | / | 自定义容器健康检查(应用探测端点为 `/`, 恒 200) |
| EventBusName | DouyinSpark-bus | EventBridge 事件总线名称(计划任务定时调度 → FC 用) |
| TaskImageUrl | ACR taskrunner 镜像 | 续火任务执行器容器镜像(aliyunFC/taskrunner) |
| TaskFunctionName / TaskTriggerName | DYSparkTaskRunner / taskTrigger | 任务执行器函数名 / 触发器名 |
| TaskCpu / TaskMemorySize | 0.5 / 512 | 任务执行器规格(CPU/MB内存, 磁盘固定 512MB) |
| TaskFunctionTimeout | 300 | 任务执行器容器最大执行时间(秒) |
| TaskContainerPort | 9000 | 任务执行器容器监听端口 |
| ApiBaseUrl / ServiceToken | 空 | 任务函数访问的 FastAPI 基址 / 机器身份服务令牌(部署填) |
| BearerToken | 空 | Bearer 令牌：FC 触发器(authType=function tokens)校验 + EventBridge Connection 注入 Authorization 头, 两者一致(务必设随机值) |
| RuleName / ApiDestinationName / ConnectionName | DouyinSpark-* | 定时调度规则 / API 端点 / 连接配置 名称 |

## 输出

| 输出 | 说明 |
|---|---|
| TriggerUrlInternet / TriggerUrlIntranet | 浏览器 Web 触发器公网 / 内网访问地址 |
| FunctionName | 浏览器函数名称 |
| EventBusName | EventBridge 事件总线名称(计划任务定时调度用) |
| TaskFunctionName | 续火任务执行器函数名称 |
| TaskTriggerUrlInternet | 任务执行器 HTTP 触发器公网地址(API 端点指向它) |
| ScheduleRuleName / ScheduleRuleARN | 定时调度规则 名称 / ARN |
| ApiDestinationName / ConnectionName | EventBridge API 端点 / 连接配置 名称 |

> 会话亲和说明: 客户端请求需携带名为 `sessionid` 的 HTTP 头, FC 基于该头哈希路由到同一实例。
> 镜像在 FC 同地域 ACR 个人版仓库, 函数通过默认网卡访问公网。