# 更新记录

## 0.3.1 (2026-09-05)

- 修复健康检查路径: 应用健康端点是 `GET /`(恒 200), 原默认 `/healthz` 无路由导致 FC 健康检查失败、实例无法唤醒(`FunctionNotStarted`/412), 默认值改为 `/`

## 0.3.0 (2026-09-05)

- 移除全部 Terraform 文件(main/network/fc/variables/outputs/versions.tf、terraform.tfvars.example、.terraform.lock.hcl、.terraform/), 只保留 ROS 原生模板方案
- readme.md 重构为纯 ROS 说明: 栈名 DouyinSpark、名称前缀 DouyinSpark、函数 DYSparkCloakBrowser
- 网络出口改为固定公网 IP: `InternetAccess: false`(关闭默认网卡公网访问, 强制走 VPC NAT → EIP 固定出口), 删除 InternetAccess 参数(26→24 参数)

## 0.2.1 (2026-09-05)

- 修复: 会话亲和函数 `instanceConcurrency` 强制为 200(FC 平台要求 ConcurrencyLimit=200), 原模板默认 1 导致 Function 创建失败 `ConcurrencyLimit is invalid for session function`
- ROS 模板移除 `InstanceConcurrency` 参数, 函数属性直接固定为 200; 实际并发仍由 `SessionConcurrencyPerInstance`(=1) 控制
- Terraform 同步: `instance_concurrency` 默认值 1 → 200
- 参数默认值更新: NamePrefix=DouyinSpark, FunctionName=DYSparkCloakBrowser

## 0.2.0 (2026-09-05)

- 新增 ROS 原生单文件模板 `ros-template.yaml`(主交付): 一个完整 YAML, 可直接粘贴阿里云 ROS 面板创建资源栈
- 用 ROS 原生模板原生解决会话亲和: `ALIYUN::FC3::Function` 的 `SessionAffinity: HEADER_FIELD` + 平铺结构的 `SessionAffinityConfig`(affinityHeaderFieldName/sessionTTLInSeconds/sessionIdleTimeoutInSeconds/sessionConcurrencyPerInstance/disableSessionIdReuse)
- 绕开 ROS 托管 Terraform 的 alicloud provider 版本上限(1.254.0)不支持 session_affinity(需 >=1.256.0)的限制
- 资源全覆盖: `ALIYUN::ECS::VPC`/`VSwitch`/`SecurityGroup`(内联 egress 0.0.0.0/0) + `ALIYUN::VPC::NatGateway`(Enhanced)/`EIP`/`EIPAssociation`/`SnatEntry`(SNatTableId 单数 GetAtt、EipAddress) + `ALIYUN::RAM::Role`(fc.aliyuncs.com 信任, Arn GetAtt)/`AttachPolicyToRole`(AliyunLogFullAccess、AliyunECSNetworkInterfaceManagementAccess) + `ALIYUN::FC3::Function`(custom-container, 9000 端口, 健康检查 /healthz, 1vCPU/1536MB/10240MB, 600s 超时, 实例并发/会话并发 1) + `ALIYUN::FC3::Trigger`(http, UrlInternet/UrlIntranet 输出)
- 参数化 26 个参数(地域/可用区/网段/镜像/规格/亲和/EIP 带宽/健康检查等), 默认值与 Terraform 方案一致
- readme.md 重构: ROS 面板部署步骤 + 在线 Vue 生成器对接说明(读 ros-template.yaml → 替换 Parameters 默认值 → 输出 YAML)

## 0.1.0 (2026-09-05)

- 改造为纯 Terraform 部署方案, 彻底移除 Serverless Devs 文件(publish.yaml / hook / src)
- 新增 `main.tf` / `network.tf` / `fc.tf` / `variables.tf` / `outputs.tf` / `versions.tf`
- 全量资源一键创建: VPC + 交换机 + 安全组 + NAT 网关 + EIP(固定公网出口) + SNAT + RAM 角色 + FC3 函数 + Web 触发器
- 函数规格: 1 vCPU / 1536 MB / 10240 MB, 容器端口 9000, 默认启动命令, 超时 600s
- 开启 HEADER_FIELD 会话亲和(键名 sessionid, TTL 600s, 空闲 30s, 单实例并发/会话并发 1, 无常驻实例)
- 模板参数化: region/zone/镜像/规格/亲和/EIP 带宽等全部可调
- 输出: EIP ID、固定公网 IP、触发器公网/内网地址

## 0.0.1 (2026-09-05)

- 初始版本: 按 Serverless Devs 应用规范建立目录结构
  - `publish.yaml`: 应用模型元数据与 Parameters 参数定义
  - `src/s.yaml`: FC3 自定义容器应用描述(ACR 镜像 + HTTP 触发器)
  - `hook/index.js`: s init 钩子
- 支持通过 `s init` / `s deploy` 快速创建 cloakbrowser 云函数
  (该版本已被 0.1.0 Terraform 方案取代)