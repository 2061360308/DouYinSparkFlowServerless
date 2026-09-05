# demo — 纯 URL 直连 + 人类操作模拟

一个可直接运行的最小客户端示例：**不使用阿里云 AK/SK**，仅凭公网 URL 完成
「构造两个头 → `GET /start` 懒启动 → Playwright `connect_over_cdp` 直连 →
`cloakbrowser` 人类操作模拟 → 截图」。

协议与端点细节见 [../docs/usage.md](../docs/usage.md)。

## 依赖（客户端）

```bash
pip install playwright cloakbrowser
playwright install chromium   # 仅为获取 Playwright 驱动; 直连远端 CDP, 不会启动本地浏览器
```

> `cloakbrowser` 仅用于 `humanize`（人类化鼠标/键盘/滚动）这一 wrapper 层能力；
> 客户端**不会**下载/启动 Chromium 二进制（浏览器在远端 FC 实例上）。
> stealth 指纹补丁在服务端二进制里，over CDP 自动生效。

## 运行

```bash
python demo/connect_demo.py https://<xxx>.cn-<region>.fcapp.run \
    '{"seed":"demo-1","timezone":"Asia/Shanghai","locale":"zh-CN"}'
```

或用环境变量：

```bash
export FC_PUBLIC_BASE=https://<xxx>.cn-<region>.fcapp.run
export DEMO_CFG_JSON='{"seed":"demo-1","timezone":"Asia/Shanghai","locale":"zh-CN"}'
python demo/connect_demo.py
```

## 可选环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FC_PUBLIC_BASE` | — | 云函数公网入口（也可作第 1 个命令行参数） |
| `DEMO_CFG_JSON` | `{"seed":"demo-1",...}` | 浏览器配置（也可作第 2 个命令行参数） |
| `DEMO_TARGET_URL` | `https://www.bing.com` | 打开的目标站 |
| `DEMO_SEARCH_QUERY` | `cloakbrowser` | 有搜索框时人类化输入的查询词 |
| `DEMO_HUMAN_PRESET` | `default` | 人类化预设：`default` / `careful` |
| `DEMO_SEQ` | `0` | 会话序号；想要**全新身份实例**就 `+1` 重跑 |

## 关键点

- **两个头**：`sessionID = sha256(JSON(cfg+seq))`（每个请求都带）、
  `X-Browser-Cfg = base64url(JSON cfg)`（仅 `/start`）。
- **人类模拟一行开启**：`patch_browser_async(browser, resolve_config("default"))`
  （同步函数，勿 `await`）。之后用 `page.fill(sel,..)` / `page.click(sel)` /
  `page.hover(sel)` 等**基于 selector** 的 API 才会走人类化管线；直接操作
  `ElementHandle` 会绕过补丁。
- **关闭语义**：`connect_over_cdp` 下 `browser.close()` 只断开连接，服务端浏览器
  保留复用；换新身份用 `DEMO_SEQ+1`，立即停实例需服务端调用 FC `DeleteSession`
  （那一步才需 AK），否则由 FC 空闲回收兜底。
