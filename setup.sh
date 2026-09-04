#!/usr/bin/env bash
#
# setup.sh — CloakBrowser 项目一键环境初始化
#
#   1) 创建虚拟环境 .venv 并安装 Python 依赖
#   2) 下载 CloakBrowser（GitHub 加速镜像）解压到仓库根 cloakbrowser/
#   3) 通过 USTC Debian 镜像补齐 Chrome 运行所需系统库（Debian / Ubuntu）
#   4) 安装 CodeBuddy Skill: alibabacloud-find-skills（阿里云 Skills 市场）
#
# 用法:
#   ./setup.sh                              # 全流程
#   ./setup.sh --skip-system-deps           # 无 root/sudo 时跳过系统组件
#   ./setup.sh --skip-skill                 # 跳过 CodeBuddy Skill 安装
#   ./setup.sh --venv-only                  # 仅创建虚拟环境并装依赖
#   ./setup.sh --browser-only               # 仅下载浏览器
#   ./setup.sh --system-deps-only           # 仅补齐系统组件
#   ./setup.sh --skill-only                 # 仅安装 CodeBuddy Skill
#
# 常用环境变量:
#   CLOAK_CHROMIUM_VERSION=146.0.7680.177.5   浏览器版本（默认同上）
#   GH_MIRROR=https://gh.07150721.xyz         GitHub 加速前缀（置空则直连官方）
#   VENV_DIR=.venv                            虚拟环境目录名
#   SKILL_NAME=alibabacloud-find-skills       要安装的 Skill 名称
#   SKILL_DIR=~/.codebuddy/skills/<name>      Skill 安装目录
#
set -euo pipefail

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REQ_FILE="$ROOT/requirements.txt"

# 浏览器落点：与 browser/local.py find_binary() 的默认路径保持一致
CHROME_DIR="$ROOT/cloakbrowser"
CHROME_BIN="$CHROME_DIR/chrome"
TARBALL="cloakbrowser-linux-x64.tar.gz"

# ---------------------------------------------------------------------------
# 可覆盖配置
# ---------------------------------------------------------------------------
CLOAK_CHROMIUM_VERSION="${CLOAK_CHROMIUM_VERSION:-146.0.7680.177.5}"
GH_MIRROR="${GH_MIRROR:-https://gh.07150721.xyz}"

GH_REPO_PATH="CloakHQ/CloakBrowser/releases/download/chromium-v${CLOAK_CHROMIUM_VERSION}/${TARBALL}"
OFFICIAL_URL="https://github.com/${GH_REPO_PATH}"
if [ -n "$GH_MIRROR" ]; then
    DOWNLOAD_URL="${GH_MIRROR%/}/https://github.com/${GH_REPO_PATH}"
else
    DOWNLOAD_URL=""
fi

VENV_DIR="${VENV_DIR:-.venv}"
VENV_PY="$ROOT/$VENV_DIR/bin/python"
VENV_PIP="$ROOT/$VENV_DIR/bin/pip"

# CodeBuddy Skill（阿里云 Skills 市场）
SKILL_NAME="${SKILL_NAME:-alibabacloud-find-skills}"
SKILL_URL="${SKILL_URL:-https://skills.aliyun.com/api/public/skills/${SKILL_NAME}/download}"
SKILL_DIR="${SKILL_DIR:-$HOME/.codebuddy/skills/${SKILL_NAME}}"

# Chrome/Chromium 在 Debian 系常见的运行库
SYSTEM_DEPS=(
    ca-certificates curl fonts-liberation
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0
    libcairo2 libcups2 libdbus-1-3 libdrm2 libexpat1 libfontconfig1
    libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3
    libpango-1.0-0 libpangocairo-1.0-0
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1
    libxext6 libxfixes3 libxi6 libxkbcommon0 libxrandr2 libxrender1
    libxss1 libxtst6 xdg-utils
)

# 开关（可由命令行 flag 调整）
DO_VENV=1
DO_BROWSER=1
DO_SYSTEM=1
DO_SKILL=1
DO_MIRROR_SRC=1          # 允许把 apt 源切到 USTC 镜像
DO_FALLBACK=1            # 镜像下载失败时回退官方地址
FORCE=0                  # 强制重新下载浏览器 / 重装 Skill

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[ERR ]\033[0m %s\n' "$*" >&2; exit 1; }

SUDO_CMD=""
resolve_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        SUDO_CMD=""
    elif command -v sudo >/dev/null 2>&1; then
        SUDO_CMD="sudo"
    else
        die "需要 root 或 sudo 权限才能安装系统组件，请改用 --skip-system-deps 或手动提权执行"
    fi
}

# 以 root 权限执行命令（root 直跑；非 root 时经 sudo），避免空 SUDO_CMD 产生空命令
run_as_root() {
    if [ -z "$SUDO_CMD" ]; then
        "$@"
    else
        "$SUDO_CMD" "$@"
    fi
}

usage() {
    # 打印文件头注释（# 行），遇到首个非注释行即停止
    awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
    exit 0
}

# ---------------------------------------------------------------------------
# 1) 虚拟环境 + Python 依赖
# ---------------------------------------------------------------------------
setup_venv() {
    command -v python3 >/dev/null 2>&1 || die "未找到 python3，请先安装（Debian/Ubuntu: sudo apt-get install -y python3 python3-venv）"

    if [ -x "$VENV_PY" ]; then
        log "虚拟环境已存在: $VENV_DIR（如需重建，删除 $ROOT/$VENV_DIR 后重跑）"
    else
        log "创建虚拟环境 $VENV_DIR ..."
        if ! python3 -m venv "$ROOT/$VENV_DIR"; then
            warn "python3-venv / ensurepip 可能缺失，尝试执行: sudo apt-get install -y python3-venv"
            die "创建虚拟环境失败"
        fi
        ok "虚拟环境已创建: $ROOT/$VENV_DIR"
    fi

    log "安装 Python 依赖 (requirements.txt) ..."
    "$VENV_PIP" install -r "$REQ_FILE"
    ok "Python 依赖安装完成"
}

# ---------------------------------------------------------------------------
# 2) 下载 CloakBrowser
# ---------------------------------------------------------------------------
ensure_downloader() {
    command -v curl >/dev/null 2>&1 && return 0
    command -v wget >/dev/null 2>&1 && return 0
    die "未找到 curl / wget。可先执行 ./setup.sh --system-deps-only 自动安装 curl，再重跑本脚本"
}

fetch_url() { # $1=url  $2=输出文件；成功返回 0
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 --connect-timeout 20 --progress-bar -o "$2" "$1"
    else
        wget -q --tries=3 --timeout=30 -O "$2" "$1"
    fi
}

download_browser() {
    if [ -x "$CHROME_BIN" ] && [ "$FORCE" != 1 ]; then
        log "浏览器已存在: $CHROME_BIN（--force 可强制重新下载）"
        return 0
    fi
    local list=()
    [ -n "$DOWNLOAD_URL" ] && list+=("$DOWNLOAD_URL")
    if [ "$DO_FALLBACK" = 1 ] && [ -n "$OFFICIAL_URL" ]; then
        list+=("$OFFICIAL_URL")
    fi
    [ "${#list[@]}" -eq 0 ] && die "没有可用下载地址（GH_MIRROR 为空且已禁用官方回退）"

    local tmp_archive
    tmp_archive="$(mktemp)"
    local got=""
    for u in "${list[@]}"; do
        log "下载 $u"
        if fetch_url "$u" "$tmp_archive"; then
            got=1
            break
        fi
        warn "下载失败: $u"
        rm -f "$tmp_archive"
    done
    [ -n "$got" ] || die "所有下载源均失败"

    tar -tzf "$tmp_archive" >/dev/null 2>&1 || die "下载内容不是有效的 tar.gz 压缩包"

    local tmp_dir
    tmp_dir="$(mktemp -d)"
    tar -xzf "$tmp_archive" -C "$tmp_dir"

    # 包内结构通常是顶层 cloakbrowser/ 目录，但也兼容扁平/嵌套结构
    local chrome_found
    chrome_found="$(find "$tmp_dir" -type f -name chrome -print -quit || true)"
    [ -n "$chrome_found" ] || die "压缩包内未找到 chrome 可执行文件"

    log "安装到 $CHROME_DIR ..."
    rm -rf "$CHROME_DIR"
    mkdir -p "$ROOT"
    if [ -d "$tmp_dir/cloakbrowser" ]; then
        mv "$tmp_dir/cloakbrowser" "$CHROME_DIR"
    else
        mkdir -p "$CHROME_DIR"
        cp -a "$(dirname "$chrome_found")/." "$CHROME_DIR/"
    fi
    chmod +x "$CHROME_BIN"
    rm -rf "$tmp_dir" "$tmp_archive"
    ok "浏览器已就绪: $CHROME_BIN"
}

# ---------------------------------------------------------------------------
# 3) 系统组件（Debian / Ubuntu + USTC 镜像）
# ---------------------------------------------------------------------------
os_id=""
os_codename=""
detect_os() {
    [ -r /etc/os-release ] || return 1
    # shellcheck disable=SC1091
    . /etc/os-release
    os_id="${ID:-}"
    os_codename="${VERSION_CODENAME:-}"
    case "$os_id" in
        debian|ubuntu) return 0 ;;
        *) return 1 ;;
    esac
}

# 把现有 apt 源的主机替换为 USTC 镜像（含 deb822 .sources 与旧式 .list）
use_ustc_source() {
    [ "$DO_MIRROR_SRC" = 1 ] || return 0
    if grep -rsq 'mirrors\.ustc\.edu\.cn' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
        log "apt 源已使用 USTC 镜像，跳过改源"
        return 0
    fi

    local files=() f
    [ -f /etc/apt/sources.list ] && files+=("/etc/apt/sources.list")
    # shellcheck disable=SC2206
    files+=($(find /etc/apt/sources.list.d -type f \( -name '*.list' -o -name '*.sources' \) 2>/dev/null || true))

    local changed=0
    for f in "${files[@]}"; do
        if grep -qsE 'deb\.debian\.org|security\.debian\.org|archive\.ubuntu\.com|security\.ubuntu\.com' "$f"; then
            log "切换 apt 源为 USTC 镜像: $f（原文件备份为 $f.bak）"
            sed -i.bak -E \
                -e 's#https?://deb\.debian\.org#http://mirrors.ustc.edu.cn#g' \
                -e 's#https?://security\.debian\.org#http://mirrors.ustc.edu.cn#g' \
                -e 's#https?://archive\.ubuntu\.com/ubuntu#http://mirrors.ustc.edu.cn/ubuntu#g' \
                -e 's#https?://security\.ubuntu\.com/ubuntu#http://mirrors.ustc.edu.cn/ubuntu#g' \
                "$f"
            changed=1
        fi
    done

    # 全新环境没有任何源文件时，按 codename 写入 USTC 源
    if [ "$changed" = 0 ] && [ -n "$os_codename" ]; then
        local dst="/etc/apt/sources.list.d/ustc-${os_id}.list"
        log "未发现可替换的 apt 源，写入 USTC 源: $dst"
        {
            echo "# Generated by setup.sh (USTC mirror)"
            echo "deb http://mirrors.ustc.edu.cn/${os_id} ${os_codename} main restricted universe multiverse"
            echo "deb http://mirrors.ustc.edu.cn/${os_id} ${os_codename}-updates main restricted universe multiverse"
            if [ "$os_id" = ubuntu ]; then
                echo "deb http://mirrors.ustc.edu.cn/${os_id} ${os_codename}-security main restricted universe multiverse"
            else
                echo "deb http://mirrors.ustc.edu.cn/debian-security ${os_codename}-security main"
            fi
        } > "$dst"
        changed=1
    fi

    [ "$changed" = 1 ] || warn "未匹配到任何 apt 源文件，将使用系统默认源安装"
    return 0
}

setup_system_deps() {
    if ! detect_os; then
        warn "当前系统 ($os_id) 非 Debian/Ubuntu，跳过系统组件安装"
        return 0
    fi

    resolve_sudo

    log "配置 USTC apt 镜像源 ..."
    use_ustc_source

    log "apt-get update ..."
    run_as_root apt-get update || warn "apt-get update 失败，将尝试直接安装（可能因源不可达而失败）"

    log "安装 Chrome 运行库 ..."
    if run_as_root apt-get install -y --no-install-recommends "${SYSTEM_DEPS[@]}"; then
        ok "系统组件安装完成"
        return 0
    fi

    # 个别包在当前发行版不存在（新旧包名差异等），逐个补齐，失败的单独提示
    warn "整批安装未完全成功，逐个补齐剩余依赖 ..."
    for p in "${SYSTEM_DEPS[@]}"; do
        err="$(run_as_root apt-get install -y --no-install-recommends "$p" 2>&1)" || {
            warn "无法安装依赖包: $p"
            # 仅展示关键错误（首条含错误语义的行），避免刷屏
            printf '%s\n' "$err" | grep -iE 'error|无法|not available|does not have|unmet|E:' | head -n 3 | sed 's/^/            /'
        }
    done
    run_as_root apt-get install -y -f >/dev/null 2>&1 || true
    ok "系统组件安装完成（个别缺失包见上方警告）"
}

# ---------------------------------------------------------------------------
# 4) 安装 CodeBuddy Skill（阿里云 Skills 市场）
# ---------------------------------------------------------------------------
unzip_to_dir() { # $1=zip  $2=目标目录
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$1" -d "$2"
    else
        python3 -m zipfile -e "$1" "$2"
    fi
}

install_skill() {
    if [ -f "$SKILL_DIR/SKILL.md" ] && [ "$FORCE" != 1 ]; then
        log "Skill 已安装: $SKILL_NAME（目录 $SKILL_DIR，--force 可强制重装）"
        return 0
    fi
    command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 \
        || die "未找到 curl / wget，无法下载 Skill"

    local tmp_zip tmp_root src inner
    tmp_zip="$(mktemp)"
    tmp_root="$(mktemp -d)"

    log "下载 Skill ($SKILL_NAME): $SKILL_URL"
    if ! fetch_url "$SKILL_URL" "$tmp_zip"; then
        rm -rf "$tmp_zip" "$tmp_root"
        die "下载 Skill 失败: $SKILL_URL"
    fi

    if ! unzip_to_dir "$tmp_zip" "$tmp_root"; then
        rm -rf "$tmp_zip" "$tmp_root"
        die "解压失败，下载内容可能不是有效的 ZIP: $SKILL_URL"
    fi

    # 兼容 SKILL.md 位于压缩包根目录或嵌套子目录两种情况
    src="$tmp_root"
    if [ ! -f "$src/SKILL.md" ]; then
        inner="$(find "$tmp_root" -name SKILL.md -print -quit 2>/dev/null || true)"
        if [ -n "$inner" ]; then
            src="$(dirname "$inner")"
        else
            rm -rf "$tmp_zip" "$tmp_root"
            die "压缩包内未找到 SKILL.md，可能不是有效的 Skill 包"
        fi
    fi

    log "安装到 $SKILL_DIR ..."
    mkdir -p "$(dirname "$SKILL_DIR")" "$SKILL_DIR"
    rm -rf "$SKILL_DIR"
    cp -a "$src/." "$SKILL_DIR/"
    chmod -R u+rwX "$SKILL_DIR"
    rm -rf "$tmp_zip" "$tmp_root"
    ok "Skill 已安装: $SKILL_NAME → $SKILL_DIR（需重启对话后生效）"
}

# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------
verify_browser() {
    [ -x "$CHROME_BIN" ] || return 0
    if out="$("$CHROME_BIN" --version 2>&1)" && [ -n "$out" ]; then
        ok "浏览器可运行: $out"
    else
        warn "chrome 无法启动，常见原因：缺少系统库。可执行 ldd $CHROME_BIN 查看缺库"
        warn "补齐命令: ./setup.sh --system-deps-only（仍缺库时按 ldd 提示逐个安装）"
    fi
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
main() {
    if ! command -v python3 >/dev/null 2>&1 && [ "$DO_VENV" = 1 ]; then
        die "未找到 python3"
    fi
    if [ "${DO_VENV}" = 1 ]; then
        setup_venv
    fi
    if [ "$DO_BROWSER" = 1 ]; then
        ensure_downloader
        if [ "$FORCE" = 1 ]; then
            download_browser
        elif [ -x "$CHROME_BIN" ]; then
            ok "浏览器已存在: $CHROME_BIN（--force 可强制重新下载）"
        else
            download_browser
        fi
    fi
    if [ "$DO_SYSTEM" = 1 ]; then
        setup_system_deps
    fi
    if [ "$DO_SKILL" = 1 ]; then
        install_skill
    fi
    verify_browser
    printf '\033[1;32m\n环境初始化完成 ✔\033[0m\n'
}

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
while [ "$#" -gt 0 ]; do
    case "$1" in
        --venv-only)        DO_BROWSER=0; DO_SYSTEM=0; DO_SKILL=0 ;;
        --browser-only)     DO_VENV=0; DO_SYSTEM=0; DO_SKILL=0 ;;
        --system-deps-only) DO_VENV=0; DO_BROWSER=0; DO_SKILL=0 ;;
        --skill-only)       DO_VENV=0; DO_BROWSER=0; DO_SYSTEM=0 ;;
        --skip-system-deps) DO_SYSTEM=0 ;;
        --skip-skill)       DO_SKILL=0 ;;
        --skip-mirror-src)  DO_MIRROR_SRC=0 ;;
        --no-fallback)      DO_FALLBACK=0 ;;
        --force)            FORCE=1 ;;
        -h|--help)          usage ;;
        *) die "未知参数: $1（./setup.sh --help 查看用法）" ;;
    esac
    shift
done

main "$@"
