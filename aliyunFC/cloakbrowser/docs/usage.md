# 使用文档

面向**客户端接入方**：如何构造两个协议头、调用 HTTP/WS 端点，以及用 Playwright
直连（**不依赖阿里云 AK/SK**，仅凭公网 URL）驱动远端 stealth 浏览器，并叠加
`cloakbrowser` 的人类操作模拟。

- 开箱即用的完整脚本见 **[../demo/connect_demo.py](../demo/connect_demo.py)**。
- 服务端实现细节见 **[development.md](development.md)**。

---

## 1. 协议：两个自定义 Header

FC 的 HeaderField 会话亲和键（`sessionid`）对值有**硬限制**：1–64 字符、字符集
`^[A-Za-z0-9_][A-Za-z0-9_-]*$`（整份 base64 配置会被网关以 `400 InvalidArgument`
拒绝）。因此把"会话身份"与"浏览器配置"拆成两个头：

| Header | 内容 | 何时携带 |
| --- | --- | --- |
| `sessionID` | `sha256(JSON(cfg+seq), sort_keys)` 的 64 位 hex，即 FC 亲和会话 ID | **每个请求**（`/start`、`/json/*`、WS 握手） |
| `X-Browser-Cfg` | `base64url(JSON 浏览器配置)`，键：`seed`/`timezone`/`locale`/`proxy`/`extra_args` | **仅** `GET /start`（缺失＝服务端默认随机配置） |

语义：

- 同 `cfg+seq` → 同 `sessionID` → 亲和命中同一实例（**复用**）；
- `seq` 自增 → 新 `sessionID` → 亲和激发**全新实例**（新身份，互不串扰）；
- `sessionID` 单向不可解回配置；原始配置由客户端保留，并随 `X-Browser-Cfg`
  发给服务端。服务端只信任请求头里的 `sessionID`，**不会**校验它是否等于
  `hash(cfg)`——所以任意稳定字符串也能用，但用 `sha256(cfg)` 便于同配置天然复用。

### 浏览器配置字段

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| `seed` | `"12345"` | 指纹种子。固定 seed＝固定身份（配持久化 profile 可保登录态）；省略＝每次随机 |
| `timezone` | `"Asia/Shanghai"` | 浏览器时区（`--fingerprint-timezone`） |
| `locale` | `"zh-CN"` | 语言（`--fingerprint-locale` + `--lang`） |
| `proxy` | `"http://user:pass@host:3128"` | 出站代理（`--proxy-server`），密码明文，注意日志安全 |
| `extra_args` | `["--window-size=1920,1080"]` | 附加启动参数；`--remote-debugging-*` / `--user-data-dir` 会被服务端过滤 |

### Python 构造示例（纯标准库，无需任何 SDK）

```python
import base64
import hashlib
import json


def build_session_id(cfg_with_seq: dict) -> str:
    """会话身份 = sha256(canonical JSON(cfg + seq)) 的 64 位 hex。"""
    raw = json.dumps(cfg_with_seq, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def encode_cfg_header(base_cfg: dict) -> str:
    """X-Browser-Cfg = base64url(JSON 浏览器配置)。自定义头无 FC 字符集限制。"""
    raw = json.dumps(base_cfg, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


# 1) 浏览器配置(不含 seq、不含 None 值)
base_cfg = {"seed": "12345", "timezone": "Asia/Shanghai", "locale": "zh-CN"}

# 2) 会话身份(seq 用于"换新实例": 同 cfg 想要一个全新身份就把 seq +1)
seq = 0
session_id = build_session_id({**base_cfg, "seq": seq})   # -> 64 位 hex
cfg_header = encode_cfg_header(base_cfg)                   # -> base64url JSON

headers_start = {"sessionID": session_id, "X-Browser-Cfg": cfg_header}  # GET /start
headers_conn = {"sessionID": session_id}                                # 其余请求 / WS
```

---

## 2. HTTP / WS 端点

约定：`BASE = https://<fc公网域名>.fcapp.run`（本地为 `http://127.0.0.1:9000`）。
WS 根地址由 `BASE` 推导：`https→wss`、`http→ws`，路径 `/`。

| 端点 | 方法 | 必带头 | 说明 |
| --- | --- | --- | --- |
| `/` | GET | — | 健康检查，恒 200；body 含 `browser_status` |
| `/start` | GET | `sessionID`(+`X-Browser-Cfg`) | 懒启动入口：创建/复用/切换浏览器，返回稳定 ws 根地址 |
| `/json/version` | GET | `sessionID` | CDP 版本；`webSocketDebuggerUrl` 重写为稳定根地址 |
| `/json/list` | GET | `sessionID` | CDP 目标列表；`webSocketDebuggerUrl` 重写为 `/devtools/...` |
| `/`（根） | WS | `sessionID` | browser-level CDP 双向转发（Playwright/裸 ws 直连用） |
| `/devtools/<type>/<id>` | WS | `sessionID` | 页面/目标级 CDP 转发 |

### GET /

恒 200（FC 探活依赖它）；浏览器是否就绪只体现在 body，不影响存活判定：

```jsonc
// 浏览器尚未 /start
{
  "status": "ok",
  "service": "cloakbrowser ws proxy",
  "version": "0.1.0",                      // 镜像版本(源自 VERSION 文件)
  "listen": "0.0.0.0:9000",
  "backend_cdp": "127.0.0.1:9222",
  "browser_status": "not_created",         // not_created | starting | ready
  "hint": "GET /start 并携带 sessionID + X-Browser-Cfg 头以按需启动浏览器"
}
// 浏览器就绪后
{
  "status": "ok", "service": "...", "version": "0.1.0", "listen": "...", "backend_cdp": "...",
  "browser": "HeadlessChrome/146.0.7680.177",
  "browser_ws": "wss://<host>/",
  "browser_status": "ready"
}
```

### GET /start

懒启动入口：按 `sessionID` 确保存在匹配且 CDP 就绪的浏览器。

```bash
SID=$(printf '%s' '{"seed":"12345","timezone":"Asia/Shanghai","seq":0}' \
      | python3 -c 'import sys,hashlib;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')
CFG=$(python3 -c 'import base64,json;print(base64.urlsafe_b64encode(json.dumps(
      {"seed":"12345","timezone":"Asia/Shanghai"},sort_keys=True).encode()).decode())')

curl -i -H "sessionID: $SID" -H "X-Browser-Cfg: $CFG" "$BASE/start"
```

返回：

```jsonc
// 200 就绪
{"status":"ready","seed":"12345","ws":"wss://<host>/","browser":"HeadlessChrome/146..."}
```

| 状态码 | 含义 |
| --- | --- |
| `200` | 浏览器就绪，`ws` 为可直连的稳定根地址 |
| `400` | 缺 `sessionID`，或 `X-Browser-Cfg` 不是合法 base64url JSON 对象 |
| `409` | 本实例正被**其他活跃会话**占用且配置不同，无法切换（换实例/重试或 `seq` 自增） |
| `503` | 浏览器启动超时或失败 |
| `501` | 该进程未接管浏览器（仅当代理独立运行、无 supervisor gate 时） |

### GET /json/version

Playwright `connect_over_cdp` 会自动请求它。`webSocketDebuggerUrl` 被重写为**稳定
根地址**（不含随机 uuid），跨实例/重启均可用：

```jsonc
{
  "Browser": "HeadlessChrome/146.0.7680.177",
  "Protocol-Version": "1.3",
  "webSocketDebuggerUrl": "wss://<host>/"
}
```

> 懒启动下若**尚未** `/start`，业务端点（`/json/*` 与 WS）返回 `503 browser not
> created`；若请求的 `sessionID` 与本实例当前会话不一致，返回 `409 session
> mismatch`（亲和瞬时抖动时让客户端重试）。

---

## 3. Playwright 直连（不用阿里云 AK）

只需公网 URL + 两个头，**无需** AK/SK（AK 仅用于服务端 `ListSessions`/
`DeleteSession` 主动管理会话，直连驱动用不到）。两步接入：

1. `GET /start` 让浏览器就绪，拿到稳定 `ws`；
2. `connect_over_cdp(ws, headers={"sessionID": sid})` 直连。

```python
import asyncio
import json
import urllib.request
from playwright.async_api import async_playwright
# build_session_id / encode_cfg_header 见第 1 节

BASE = "https://<fc公网域名>.fcapp.run"
WS = "wss://<fc公网域名>.fcapp.run/"          # BASE 的 https→wss + 根路径

base_cfg = {"seed": "12345", "timezone": "Asia/Shanghai", "locale": "zh-CN"}
sid = build_session_id({**base_cfg, "seq": 0})


def start_browser() -> None:
    """第 1 步: GET /start 懒启动(仅需两个头)。"""
    req = urllib.request.Request(
        f"{BASE}/start",
        headers={"sessionID": sid, "X-Browser-Cfg": encode_cfg_header(base_cfg)},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        print("start:", json.load(resp))


async def main() -> None:
    start_browser()
    async with async_playwright() as p:
        # 第 2 步: 直连(header 只带 sessionID)
        browser = await p.chromium.connect_over_cdp(
            WS, headers={"sessionID": sid}, timeout=60_000)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://example.com", wait_until="domcontentloaded")
        print(await page.title())
        await browser.close()   # 仅断开连接; 服务端浏览器保留复用(见下)

asyncio.run(main())
```

> **关于关闭/回收**：`connect_over_cdp` 下 Playwright 不拥有远端进程，
> `browser.close()` 只断开连接，服务端浏览器仍保留（同 `sessionID` 重连直接命中）。
> 想要**新身份**：把 `seq +1` 重新算 `sessionID` 即可激发新实例。想**立即停实例**
> 需要服务端 FC `DeleteSession`（那一步才需要 AK）；不处理则由 FC 空闲回收兜底。

### 叠加 cloakbrowser 的人类操作模拟

服务端二进制自带的 stealth 指纹补丁**over CDP 自动生效**；而 `humanize`（贝塞尔
曲线鼠标、逐字符打字、平滑滚动）是 **wrapper 层**特性，直连场景需在客户端把它
"贴"到已连接的 browser 上。用 `cloakbrowser.human` 的补丁函数即可，**不会**在
客户端启动本地浏览器、也不需要下载 Chromium 二进制：

```python
# 客户端依赖: pip install playwright cloakbrowser
from cloakbrowser.human import patch_browser_async, resolve_config

browser = await p.chromium.connect_over_cdp(WS, headers={"sessionID": sid})

# 一行开启人类模拟: "default" 常规速度, "careful" 更慢更谨慎
patch_browser_async(browser, resolve_config("default"))

# 此后 page 的交互方法全部走人类化管线(现有页与后续 new_page 都会被自动 patch):
page = browser.contexts[0].pages[0]
await page.goto("https://www.example.com")
await page.hover("#login")                       # 贝塞尔轨迹移动
await page.fill("#email", "user@example.com")    # 逐字符 + 思考停顿
await page.click("button[type=submit]")          # 真实落点 + 按压时长
```

自定义人类化参数：

```python
from cloakbrowser.human import patch_browser_async, resolve_config, merge_config

cfg = merge_config(resolve_config("default"), {
    "mistype_chance": 0.05,             # 5% 打字失误并自我纠正
    "typing_delay": 100,                # 每字符延迟(ms)
    "idle_between_actions": True,       # 动作间微移动
    "idle_between_duration": [0.3, 0.8],
})
patch_browser_async(browser, cfg)
```

> **注意**：人类化只作用于**基于 selector 的 API**——`page.click(sel)` /
> `page.fill(sel)` / `page.type(sel)` / `page.hover(sel)` / `page.locator(sel).*`。
> 直接拿 `ElementHandle`（`query_selector` 返回值）操作会绕过补丁（鼠标瞬移、
> 无打字时序）。同步版用 `patch_browser` + `resolve_config`。

---

## 4. 手动两步（不依赖任何库，纯 curl）

```bash
# 1) 懒启动
curl -H "sessionID: $SID" -H "X-Browser-Cfg: $CFG" "$BASE/start"
# 2) 客户端(任意 CDP/ws 库) 直连 wss://<host>/  并在握手头带 sessionID: $SID
```
