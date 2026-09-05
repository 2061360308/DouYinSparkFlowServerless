# cloakbrowser-serverless (Serverless Devs 应用)

基于 ACR 自定义容器镜像, 快速创建阿里云函数计算 **FC3** 云函数(cloakbrowser stealth Chromium + websockets 代理)。

## 目录结构

```
install
├── src/                # 应用目录(名不可改)
│   └── s.yaml          # FC3 应用描述文件(资源/容器/触发器)
├── hook/               # s init 钩子(名不可改)
│   └── index.js
├── publish.yaml        # 应用模型元数据(registry 识别/初始化参数)
├── readme.md           # 项目简介
└── version.md          # 版本更新记录
```

## 快速创建云函数

1. 安装 Serverless Devs 并配置密钥:

```bash
npm i -g @serverless-devs/s
s config add --AccessKeyID <AK> --AccessKeySecret <SK> -a default
```

2. 初始化(将按 `publish.yaml` 的 Parameters 交互填入参数):

```bash
s init https://.../install.zip      # 或通过 Serverless Registry 初始化
# 在 src 目录下:
cd src && s deploy                  # 创建/更新云函数与 HTTP 触发器
```

3. 不使用 init 时, 可直接编辑 `src/s.yaml` 替换 `{{ }}` 变量后 `s deploy`。

## 参数说明

| 参数 | 说明 | 默认 |
|---|---|---|
| region | 函数计算地域 | cn-hangzhou |
| functionName | 函数名称 | cloakbrowser |
| imageUrl | ACR 自定义容器镜像 | 必填 |
| memorySize | 内存(MB) | 2048 |
| cpu | CPU(vCPU, 0.05 倍数) | 1 |
| timeout | 超时(秒) | 600 |

> HTTP 触发器默认 `authType: function`(需通过密钥调用), 如需公开访问改为 `anonymous`。
> 磁盘固定 10240 MB(浏览器运行需足够 /tmp 空间)。