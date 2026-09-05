# 更新记录

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