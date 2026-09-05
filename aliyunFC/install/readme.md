# DouyinSpark cloakbrowser-serverless

基于 ACR 自定义容器镜像, 一次性创建全部资源并部署 **FC3** 云函数(cloakbrowser stealth Chromium + websockets 代理), 支持 HEADER_FIELD 会话亲和与固定公网出口 IP。

部署方式: **ROS 原生模板** — 单文件 YAML, 直接在阿里云 ROS 面板粘贴部署, 原生支持会话亲和。

## 目录结构

```
install
├── ros-template.yaml     # ROS 原生单文件模板(主交付, 可粘 ROS 面板)
├── readme.md
└── version.md
```

## 一键部署 (ROS 面板)

不需要本地安装任何工具, 直接在阿里云控制台粘贴 `ros-template.yaml` 部署:

1. 打开 [资源编排 ROS 控制台](https://ros.console.aliyun.com/) → **创建资源栈** → **使用现有模板** → **模板录入方式 = 输入模板** → **模板内容类型 = YAML**, 粘贴 `install/ros-template.yaml` 内容 → 下一步。
2. 在 **配置参数** 页填写模板参数(默认值可直接使用): 地域建议 `cn-hangzhou`(默认镜像/BGP 出口所在区域), `可用区` 按所选地域调整(默认 `cn-hangzhou-b`)。**新建资源栈时输入栈名 `DouyinSpark`**(栈名是创建栈时的入参, 不写在模板里)。
3. 点击 **创建** 等待资源栈创建完成(约 2~5 分钟, 含 NAT/ENI 等资源)。
4. 在 **资源栈 → 输出** 中查看: 固定公网出口 IP(`EipIpAddress`)、Web 触发器公网地址(`TriggerUrlInternet`)。

> 注意事项:
> - 部署前请确认账号已完成 **实名认证** 并开通 FC / VPC / RAM / NAT 相关服务。
> - 会话亲和已内置(`SessionAffinity: HEADER_FIELD`), 无需额外传参, 客户端请求携带 `sessionid` 请求头即可享受亲和路由。
> - 会话函数强制 `instanceConcurrency=200`(已内置), 单实例实际并发由 `SessionConcurrencyPerInstance=1` 控制, 不影响资源占用。
> - EIP 默认按流量计费(PayByTraffic), 带宽 5 Mbps, 可在模板参数中调整。
> - 已关闭"允许函数默认网卡访问公网"(`InternetAccess: false`), 函数出网流量强制走 VPC NAT → EIP, 出口 IP 固定(对外看到的即 `EipIpAddress`)。
> - `Command`/`Entrypoint` 不填写(CustomContainerConfig 仅 Image/Port/HealthCheckConfig), 使用镜像内置启动命令。
> - 删除资源栈即可一键销毁全部资源(勾选删除保护会保留, 请按提示操作)。

## 在线 Vue 生成器对接

`ros-template.yaml` 即最终单文件模板, 在线 Vue 程序只需:

1. 读取 `install/ros-template.yaml` 内容。
2. 按用户收集的输入(地域/可用区/函数名/镜像地址/规格/亲和参数等)替换 `Parameters` 中对应字段的 `Default` 值。
3. 输出渲染后的 YAML 字符串供用户在 ROS 面板粘贴部署(或调用 ROS API 直接创建资源栈)。

无需拼接多个文件 — 模板是一个完整自包含的 YAML。资源栈名称(`StackName`)是 `CreateStack` 的入参, 不作为模板字段, 建议 Vue 端单独收集(默认 `DouyinSpark`)。

## 默认资源规格

| 资源 | 规格 |
|---|---|
| 函数 | `DYSparkCloakBrowser`, 1 vCPU / 1536 MB 内存 / 10240 MB 磁盘 |
| 容器 | `crpi-yagm0mg4gyj902wq.cn-hangzhou.personal.cr.aliyuncs.com/oilu/cloakbrowser-serverless:latest`, 端口 9000, 镜像默认启动命令 |
| 会话亲和 | HEADER_FIELD, 键名 `sessionid`, TTL 600s, 空闲 30s, 单实例会话并发 1 |
| 函数超时 | 600s |
| 并发 | 实例并发 200(会话亲和强制值) / 会话并发 1, 无常驻实例 |
| 触发器 | Web(HTTP) 触发器, 默认 `anonymous`, 方法 GET/POST/PUT/DELETE/HEAD |
| 公网出口 | 新建 VPC + NAT 网关(Enhanced) + EIP + SNAT, EIP 带宽 5 Mbps(默认按流量计费), 全量固定公网 IP |
| 名称前缀 | `DouyinSpark`(VPC/NAT/EIP/安全组/RAM 角色等资源名) |

## 模板参数说明(ROS Parameters)

| 参数 | 默认 | 说明 |
|---|---|---|
| NamePrefix | DouyinSpark | 资源名称前缀(VPC/NAT/EIP/安全组/角色) |
| ZoneId | cn-hangzhou-b | 交换机可用区 |
| VpcCidrBlock / VSwitchCidrBlock | 172.16.0.0/16 / 172.16.0.0/24 | VPC / 交换机网段 |
| FunctionName | DYSparkCloakBrowser | 函数名称 |
| ImageUrl | ACR 镜像 | 容器镜像地址 |
| Cpu / MemorySize / DiskSize | 1 / 1536 / 10240 | 函数规格(CPU/MB内存/MB磁盘) |
| FunctionTimeout | 600 | 容器最大执行时间(秒) |
| ContainerPort | 9000 | 容器监听端口 |
| TriggerName / TriggerAuthType | webTrigger / anonymous | 触发器名称 / 鉴权方式 |
| SessionAffinityHeaderFieldName | sessionid | 亲和请求头名 |
| SessionTTLSeconds / SessionIdleTimeoutSeconds | 600 / 30 | 会话生命周期 / 空闲等待(秒) |
| SessionConcurrencyPerInstance | 1 | 单实例最大 Session 数 |
| DisableSessionIdReuse | false | Session 过期后拒绝复用 |
| HealthCheckUrl / 健康检查 | / | 自定义容器健康检查(应用探测端点为 `/`, 恒 200) |
| EipBandwidth / EipInternetChargeType | 5 / PayByTraffic | EIP 带宽(Mbps) / 计费方式 |

## 输出

| 输出 | 说明 |
|---|---|
| EipId / EipIpAddress | 固定公网出口 EIP 实例 ID / 公网 IP |
| TriggerUrlInternet / TriggerUrlIntranet | Web 触发器公网 / 内网访问地址 |
| NatGatewayId / VpcId / VSwitchId / SecurityGroupId | 相关资源 ID |
| FunctionName | 函数名称 |

> 会话亲和说明: 客户端请求需携带名为 `sessionid` 的 HTTP 头, FC 基于该头哈希路由到同一实例。
> 镜像在 FC 同地域 ACR 个人版仓库, VPC 内自动走 EIP 固定出口出网。