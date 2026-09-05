# 更新记录

## 0.0.1 (2026-09-05)

- 初始版本: 按 Serverless Devs 应用规范建立目录结构
  - `publish.yaml`: 应用模型元数据与 Parameters 参数定义
  - `src/s.yaml`: FC3 自定义容器应用描述(ACR 镜像 + HTTP 触发器)
  - `hook/index.js`: s init 钩子
- 支持通过 `s init` / `s deploy` 快速创建 cloakbrowser 云函数