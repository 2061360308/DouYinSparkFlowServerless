# =============================================================================
# CloakBrowser(免费版 Chromium 二进制) + 最简 WS 转发 容器镜像
#
# 架构:
#   stealth Chromium (remote debugging, 仅监听 127.0.0.1:9222)
#        ^
#        | 纯 websockets 代理 (0.0.0.0:9000)
#        |
#   外部 CDP 客户端 (Playwright connect_over_cdp / Puppeteer / 任意 ws 客户端)
#
# 极简原则(镜像尽量小):
#   - 不装任何 wrapper/驱动: Chromium 二进制直接从 CloakBrowser 官方
#     GitHub Release 下载(v146 keyless 免费版, 构建期 sha256 校验),
#     stealth 启动参数(--fingerprint=<seed> --fingerprint-platform=windows
#     等, 上游默认集即此 3 项)由 app/browser.py 原生生成;
#   - 第三方 Python 依赖只有 websockets 一个(HTTP 探活/列表用标准库实现);
#   - 默认 headless(无需 Xvfb), 适配阿里云函数计算等无头平台;
#   - 默认预置 Windows 默认字体(伪装 Windows 的字体指纹自洽, 见第 2 步:
#     ENABLE_WINDOWS_FONTS=false 可跳过以省 ~230MB 镜像体积)。
#
# 国内构建节点适配:
#   - 无 docker.io 依赖: 基础镜像走 DaoCloud 公共代理, pip 走阿里云,
#     Chromium/Windows 字体均走 GitHub 加速镜像(CNB/ACR 节点已验证可 clone github.com);
#   - 不用 # syntax=docker/dockerfile:1(BuildKit 前端镜像会从 docker.io 拉取)。
# =============================================================================
ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
FROM ${PYTHON_IMAGE}

# ---- 镜像版本(单一事实来源: 仓库根目录的 VERSION 文件) ---------------------
# 构建时注入: docker build --build-arg IMAGE_VERSION="$(cat VERSION)" ...
# 未传则用 0.0.0-dev 兜底(标记为未正式版本化的构建)。
ARG IMAGE_VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="cloakbrowser-serverless" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.description="keyless stealth Chromium(remote debugging) + websockets 代理, 适配阿里云函数计算(FC)"

# ---- 可覆盖的构建参数 ------------------------------------------------------
# CloakBrowser 免费版 Chromium 版本(v146 = wrapper 0.5.10 对应发布)
ARG CLOAK_CHROMIUM_VERSION=146.0.7680.177.5
# 官方 release asset 的 sha256(构建期校验, 防下载被篡改)
ARG CLOAK_BINARY_SHA256=4a12bcde95fa1bb1beef2b41ab5e5c27c36be78e3be3d0dac8c64d705216670e
# Chromium 下载源(逐个 fallback, 直到成功):
#   1. CLOAK_DOWNLOAD_URL    完整自定义 URL(自建内网/OSS 镜像最优先)
#   2. CLOAK_DOWNLOAD_MIRRORS  GitHub 加速镜像前缀列表(空格分隔), 依次拼在官方
#      直链前尝试, 例: https://ghfast.top/ https://gh-proxy.com/
#   3. 官方直链 https://github.com/... (最后兜底)
# 国内 ACR/CNB 构建节点直连 github.com 下载 207MB 大文件经常极慢/超时,
# 默认开启常用加速镜像; 仍失败请在 ACR 构建参数里换用自建源或其它可用代理。
ARG CLOAK_DOWNLOAD_URL=""
ARG CLOAK_DOWNLOAD_MIRRORS="https://gh.07150721.xyz/ https://ghfast.top/ https://gh-proxy.com/ https://ghproxy.net/"
# 单个下载源的总超时(秒): 加速镜像一般几分钟内完成, 官方直连慢时会卡满此值
ARG CLOAK_DOWNLOAD_TIMEOUT=600
# 是否安装 headed 模式依赖(Xvfb/openbox/xdotool), 默认不装(镜像更小)
ARG ENABLE_HEADED=false
# pip 镜像源(默认阿里云; 也可换腾讯云/清华源)
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
# apt 镜像源(默认中科大 debian 源 http://mirrors.ustc.edu.cn/debian; 也可换清华/腾讯云源)
# 仅填域名即可: 下方 sed 会整站替换 deb.debian.org / security.debian.org
ARG APT_MIRROR=mirrors.ustc.edu.cn

# 是否预置 Windows 默认字体(防检测关键: 伪装成 Windows 却缺 Segoe UI/
# 微软雅黑 等字体 = 明显的机器特征, 字体指纹一看就露馅, 见 README"字体"一节)。
# 默认从 GitHub 仓库 ErwinLiYH/all_win10_fonts(约 230MB/348 个文件, 与原
# C:\Windows\Fonts 一致)下载并 fc-cache 打进镜像; 设 false 可跳过。
ARG ENABLE_WINDOWS_FONTS=true
# 完整自定义 URL(自建内网/OSS 镜像最优先); 为空则用下方加速镜像拉官方包
ARG WINDOWS_FONTS_URL=""
# Windows 字体官方 tarball(可整体替换为其它全套字体仓库)
ARG WINDOWS_FONTS_ARCHIVE="https://github.com/ErwinLiYH/all_win10_fonts/archive/refs/heads/main.tar.gz"
# 字体下载加速镜像前缀(空格分隔), 依次拼在官方 tarball 前尝试
ARG WINDOWS_FONTS_MIRRORS="https://gh.07150721.xyz/ https://ghfast.top/ https://gh-proxy.com/ https://ghproxy.net/"
# 可选: 字体 tarball 的 sha256(首次构建后 sha256sum 计算并回填, 此后强校验)
ARG WINDOWS_FONTS_SHA256=""
# 单个字体下载源的总超时(秒)
ARG WINDOWS_FONTS_TIMEOUT=600

# ---- 1. 系统运行库(Chromium 最小依赖集; 字体另见第 2 步) --------------------
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    else \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdbus-1-3 libdrm2 libxkbcommon0 libatspi2.0-0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libx11-xcb1 libfontconfig1 libx11-6 \
    libxcb1 libxext6 libxshmfence1 libglib2.0-0 libgtk-3-0 \
    libpangocairo-1.0-0 libcairo-gobject2 libgdk-pixbuf-2.0-0 \
    libxss1 libxtst6 fonts-liberation \
    fontconfig \
    curl ca-certificates \
    && if [ "${ENABLE_HEADED}" = "true" ]; then \
         apt-get install -y --no-install-recommends xvfb xdotool openbox; \
       fi \
    && rm -rf /var/lib/apt/lists/*

# ---- 2. Windows 默认字体(Segoe UI/Calibri/微软雅黑/宋体/...) -----------------
# 伪装成 Windows 却缺 Windows 字体, 是字体指纹(measureText / document.fonts /
# 字体枚举)的明显破绽(FingerprintJS / CreepJS / Kasada 即以此判机器)。
# 构建期把全套 Windows 字体预置进镜像并 fc-cache, 让 Linux 上实际可检测到的
# 字体集与 Windows persona 自洽。MS 字体为专有授权, 请仅用于私有镜像/自用。
RUN set -eux; \
    if [ "${ENABLE_WINDOWS_FONTS}" != "true" ]; then \
      echo "==> ENABLE_WINDOWS_FONTS=false: 跳过 Windows 字体(防检测能力下降)"; \
    else \
      urls=""; \
      if [ -n "${WINDOWS_FONTS_URL}" ]; then \
        urls="${WINDOWS_FONTS_URL}"; \
      else \
        for m in ${WINDOWS_FONTS_MIRRORS}; do urls="${urls} ${m}${WINDOWS_FONTS_ARCHIVE}"; done; \
        urls="${urls} ${WINDOWS_FONTS_ARCHIVE}"; \
      fi; \
      ok=0; \
      for u in ${urls}; do \
        echo "==> 尝试下载 Windows 字体: ${u}"; \
        if curl -fL --connect-timeout 15 --max-time "${WINDOWS_FONTS_TIMEOUT}" \
             --retry 2 --retry-delay 2 -o /tmp/winfonts.tar.gz "${u}"; then \
          if [ -z "${WINDOWS_FONTS_SHA256}" ] || (echo "${WINDOWS_FONTS_SHA256}  /tmp/winfonts.tar.gz" | sha256sum -c - >/dev/null 2>&1); then \
            echo "==> Windows 字体下载成功: ${u}"; ok=1; break; \
          else \
            echo "==> sha256 校验不符, 换下一个源..."; \
          fi; \
        else \
          echo "==> 该源失败(下载错误), 换下一个源..."; \
        fi; \
      done; \
      [ "${ok}" = "1" ] || { echo "所有字体下载源均失败, 请配置 WINDOWS_FONTS_URL/ARCHIVE/MIRRORS" >&2; exit 1; }; \
      mkdir -p /tmp/winfont_extract /usr/share/fonts/truetype/windows; \
      tar -xzf /tmp/winfonts.tar.gz -C /tmp/winfont_extract; \
      rm -f /tmp/winfonts.tar.gz; \
      find /tmp/winfont_extract -type f \( -iname "*.ttf" -o -iname "*.ttc" -o -iname "*.otf" \) -exec cp -n {} /usr/share/fonts/truetype/windows/ \; ; \
      rm -rf /tmp/winfont_extract; \
      fc-cache -f >/dev/null 2>&1 || true; \
      echo "==> 已安装 Windows 字体(fc-list 前 5 行):"; fc-list | head -n 5; \
      if ! fc-list | grep -qiE 'segoe ui|microsoft yahei|simsun|calibri'; then \
        echo "警告: fc-list 中未检测到关键 Windows 字体, 请检查 WINDOWS_FONTS_* 配置" >&2; \
      fi; \
    fi

# ---- 3. 下载免费版 stealth Chromium(GitHub Release, 构建期预置进镜像) ------
# 运行时不再联网; 解压后二进制固定在 /opt/cloakbrowser/chrome
# 下载源依次尝试: 自定义 URL -> 加速镜像 -> 官方直链, 全部失败才报错退出
RUN set -eux; \
    tag="chromium-v${CLOAK_CHROMIUM_VERSION}"; \
    path="CloakHQ/CloakBrowser/releases/download/${tag}/cloakbrowser-linux-x64.tar.gz"; \
    github_url="https://github.com/${path}"; \
    urls=""; \
    if [ -n "${CLOAK_DOWNLOAD_URL}" ]; then urls="${CLOAK_DOWNLOAD_URL}"; fi; \
    if [ -n "${CLOAK_DOWNLOAD_MIRRORS}" ]; then \
      for m in ${CLOAK_DOWNLOAD_MIRRORS}; do urls="${urls} ${m}${github_url}"; done; \
    fi; \
    urls="${urls} ${github_url}"; \
    ok=0; \
    for u in ${urls}; do \
      echo "==> 尝试下载: ${u}"; \
      if curl -fL --connect-timeout 15 --max-time "${CLOAK_DOWNLOAD_TIMEOUT}" \
           --retry 2 --retry-delay 2 -o /tmp/cb.tar.gz "${u}" \
         && echo "${CLOAK_BINARY_SHA256}  /tmp/cb.tar.gz" | sha256sum -c - >/dev/null 2>&1; then \
        echo "==> 下载成功且 sha256 校验通过: ${u}"; ok=1; break; \
      else \
        echo "==> 该源失败(下载错误或校验不符), 换下一个源..."; \
      fi; \
    done; \
    [ "${ok}" = "1" ] || { echo "所有下载源均失败, 请换 CLOAK_DOWNLOAD_URL/MIRRORS" >&2; exit 1; }; \
    echo "${CLOAK_BINARY_SHA256}  /tmp/cb.tar.gz" | sha256sum -c -; \
    mkdir -p /tmp/cb_extract /opt/cloakbrowser; \
    # 必须先解压再删除, 否则 tar 找不到文件(exit 2)
    tar -xzf /tmp/cb.tar.gz -C /tmp/cb_extract; \
    rm -f /tmp/cb.tar.gz; \
    chrome="$(find /tmp/cb_extract -maxdepth 6 -type f -name chrome -perm -u+x | head -n 1)"; \
    test -n "${chrome}" || { echo "chrome binary not found in archive" >&2; exit 1; }; \
    chromedir="$(dirname "${chrome}")"; \
    echo "==> chrome binary: ${chrome}"; \
    echo "==> chromedir files:"; ls -la "${chromedir}"; \
    # Chromium 非自包含: 必须与 icudtl.dat/.pak/locales/ 等辅助文件同目录,
    # 只拷 chrome 单文件会在启动时因缺 ICU 数据崩溃(SIGTRAP)。整目录平铺拷贝。
    cp -a "${chromedir}/." /opt/cloakbrowser/; \
    chmod +x /opt/cloakbrowser/chrome; \
    rm -rf /tmp/cb_extract; \
    test -f /opt/cloakbrowser/icudtl.dat \
      || { echo "致命: /opt/cloakbrowser 下缺少 icudtl.dat(Chromium 启动必需), 请检查发布包布局" >&2; exit 1; }; \
    echo "==> /opt/cloakbrowser:"; ls -la /opt/cloakbrowser | head -30; \
    echo "==> binary check:"; /opt/cloakbrowser/chrome --version

# ---- 4. 唯一的第三方 Python 依赖: websockets(HTTP/WS 代理) ------------------
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} "websockets==17.1"

# ---- 5. 本仓库代码: 编排器 + 浏览器启动 + 转发代理 --------------------------
WORKDIR /app
COPY VERSION ./VERSION
COPY app/ ./app/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 默认 headless, 不依赖 Xvfb(阿里云 FC 等平台友好);
# 设 BROWSER_HEADLESS=false 走 headed(需 ENABLE_HEADED=true 构建)
# IMAGE_VERSION 由构建参数透传为运行时 ENV, 供 app 读取并在 GET / 上报版本
ENV PROXY_PORT=9000 \
    CDP_PORT=9222 \
    BROWSER_HEADLESS=true \
    DISPLAY=:99 \
    IMAGE_VERSION=${IMAGE_VERSION} \
    CLOAKBROWSER_BINARY_PATH=/opt/cloakbrowser/chrome

# FC 要求容器 HTTP 服务监听 0.0.0.0:9000
EXPOSE 9000

ENTRYPOINT ["/entrypoint.sh"]
