# cloakbrowser-serverless (Terraform 部署)

基于 ACR 自定义容器镜像, 使用 **阿里云 Terraform** 一次性创建全部资源并部署 **FC3** 云函数(cloakbrowser stealth Chromium + websockets 代理)。

## 目录结构

```
install
├── main.tf               # provider + 会话亲和配置(locals)
├── network.tf            # VPC / 交换机 / 安全组 / NAT / EIP / SNAT(固定公网出口)
├── fc.tf                 # RAM 角色 + FC3 函数(自定义容器) + Web 触发器
├── variables.tf          # 全部模板参数(参数化, 可复用)
├── outputs.tf            # 输出: EIP ID / 触发器公网地址等
├── versions.tf           # Terraform 与 alicloud provider 版本约束
├── terraform.tfvars.example
├── readme.md
└── version.md
```

## 一键部署

前置: Terraform >= 1.5, 已配置阿里云 AccessKey。

```bash
# 1. 配置密钥(环境变量)
export ALIBABA_CLOUD_ACCESS_KEY_ID=<AK>
export ALIBABA_CLOUD_ACCESS_KEY_SECRET=<SK>

# 2. 复制参数文件并按需修改
cp terraform.tfvars.example terraform.tfvars

# 3. 初始化并预览
terraform init
terraform plan

# 4. 创建资源(一次性创建 VPC/NAT/EIP/安全组/RAM角色/函数/触发器)
terraform apply -auto-approve

# 5. 查看输出(公网出口 EIP ID、触发器公网地址)
terraform output
```

## 默认资源规格

| 资源 | 规格 |
|---|---|
| 函数 | 1 vCPU / 1536 MB 内存 / 10240 MB 磁盘 |
| 容器 | `crpi-yagm0mg4gyj902wq.cn-hangzhou.personal.cr.aliyuncs.com/oilu/cloakbrowser-serverless:latest`, 端口 9000, 默认启动命令 |
| 会话亲和 | HEADER_FIELD, 键名 `sessionid`, TTL 600s, 空闲 30s, 单实例并发 1 |
| 函数超时 | 600s |
| 并发 | 实例并发 1 / 会话并发 1, 无常驻实例 |
| 触发器 | Web(HTTP) 触发器, 默认 `anonymous`, 方法 GET/POST/PUT/DELETE/HEAD |
| 公网出口 | 新建 VPC + NAT 网关(Enhanced) + EIP + SNAT, EIP 带宽 5 Mbps(默认按流量计费), 全量固定公网 IP |

## 删除资源

```bash
terraform destroy -auto-approve
```

## 参数说明(详见 variables.tf)

| 参数 | 默认 | 说明 |
|---|---|---|
| region | cn-hangzhou | 地域(EIP 出口/函数所在地区) |
| zone_id | cn-hangzhou-b | 交换机可用区 |
| function_name | cloakbrowser | 函数名称 |
| image_url | ACR 镜像 | 容器镜像地址 |
| cpu / memory_size / disk_size | 1 / 1536 / 10240 | 函数规格(CPU/MB内存/MB磁盘) |
| function_timeout | 600 | 容器最大执行时间(秒) |
| instance_concurrency | 1 | 实例并发度 |
| container_port | 9000 | 容器监听端口 |
| trigger_auth_type | anonymous | anonymous / function |
| session_affinity_header_field_name | sessionid | 亲和请求头名 |
| session_ttl_seconds | 600 | 会话最长生命周期(秒) |
| session_idle_timeout_seconds | 30 | 会话空闲等待时间(秒) |
| session_concurrency_per_instance | 1 | 单实例最大 Session 数 |
| eip_bandwidth | 5 | EIP 带宽(Mbps) |
| eip_internet_charge_type | PayByTraffic | 按流量 / 按带宽计费 |
| vpc_cidr_block | 172.16.0.0/16 | VPC 网段 |
| vswitch_cidr_block | 172.16.0.0/24 | 交换机网段 |

## 输出

| 输出 | 说明 |
|---|---|
| eip_id | 固定公网出口 EIP 实例 ID |
| eip_ip_address | 固定公网出口公网 IP |
| trigger_url_internet | Web 触发器公网访问地址 |
| trigger_url_intranet | Web 触发器内网访问地址 |

> 会话亲和说明: 客户端请求需携带名为 `sessionid` 的 HTTP 头, FC 基于该头哈希路由到同一实例。
> 会话亲和配置通过 `session_affinity_config`(jsonencode 的 HTTPHeaderFieldSessionAffinityConfig) 透传。
> 镜像在 FC 同地域 ACR 个人版仓库, VPC 内自动走 EIP 固定出口出网。