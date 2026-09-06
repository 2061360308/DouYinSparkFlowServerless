#!/usr/bin/env bash
#
# 以 Web 界面模式启动 opencode(浏览器访问, 无 TUI/鼠标乱码问题)。
#
# 用法:
#   ./start-opencode-web.sh             # 后台启动, 密码自动生成
#   OPENCODE_PASSWORD=xxx ./start-opencode-web.sh
#   PORT=5000 BIND_HOST=0.0.0.0 ./start-opencode-web.sh
#   FOREGROUND=1 ./start-opencode-web.sh    # 前台运行(不 nohup)
#   STOP=1 ./start-opencode-web.sh          # 停止之前启动的实例
#   STATUS=1 ./start-opencode-web.sh        # 查看运行状态
#
# 常用环境变量(均有默认值):
#   BIND_HOST  默认 0.0.0.0   (0.0.0.0 允许外网访问; 仅本机用 127.0.0.1)
#   PORT       默认 4096
#   OPENCODE_PASSWORD  为空则自动生成并持久化到 ~/.config/opencode/web_password
#
# 注意: 不要用 HOSTNAME 当变量名, bash 内置 HOSTNAME 就是主机名, 会覆盖默认值。
set -euo pipefail

PORT="${PORT:-4096}"
BIND_HOST="${BIND_HOST:-0.0.0.0}"
OC="${OPENCODE_BIN:-$HOME/.opencode/bin/opencode}"
PIDFILE="$HOME/.config/opencode/web.pid"
LOGFILE="$HOME/.config/opencode/web.log"
PWFILE="$HOME/.config/opencode/web_password"

mkdir -p "$(dirname "$PIDFILE")"

if [ "${STOP:-0}" = "1" ]; then
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")"
    echo "[opencode-web] 已停止 PID $(cat "$PIDFILE")"
  else
    echo "[opencode-web] 没有运行中的实例"
  fi
  rm -f "$PIDFILE"
  exit 0
fi

if [ "${STATUS:-0}" = "1" ]; then
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "[opencode-web] 运行中: http://$BIND_HOST:$PORT (PID $(cat "$PIDFILE"), 日志 $LOGFILE)"
  else
    echo "[opencode-web] 未运行"
  fi
  exit 0
fi

if [ ! -x "$OC" ]; then
  echo "[opencode-web] 找不到 opencode: $OC (可用 OPENCODE_BIN 指定路径)" >&2
  exit 1
fi
if ! "$OC" --version >/dev/null 2>&1; then
  echo "[opencode-web] opencode 不可用, 请检查安装/网络" >&2
  exit 1
fi

# ---- 密码: 环境优先; 否则复用/生成并持久化 ----
if [ -n "${OPENCODE_PASSWORD:-}" ]; then
  export OPENCODE_SERVER_PASSWORD="$OPENCODE_PASSWORD"
elif [ -f "$PWFILE" ]; then
  export OPENCODE_SERVER_PASSWORD="$(cat "$PWFILE")"
else
  P="$(head -c16 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c12)"
  umask 077
  printf '%s' "$P" > "$PWFILE"
  export OPENCODE_SERVER_PASSWORD="$P"
  echo "[opencode-web] 已生成密码: $P (保存在 $PWFILE)"
fi

# ---- 已在监听则提示并退出 (curl 必须绕开 http_proxy, 否则会被代理劫持为"已有服务") ----
if curl -s -m 2 --noproxy '*' -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo "[opencode-web] 端口 $PORT 已有服务在响应, 不改动"
  exit 0
fi

if [ "${FOREGROUND:-0}" = "1" ]; then
  echo "[opencode-web] 前台启动: http://$BIND_HOST:$PORT (密码见上方, Ctrl+C 停止)"
  exec "$OC" web --hostname "$BIND_HOST" --port "$PORT"
else
  nohup "$OC" web --hostname "$BIND_HOST" --port "$PORT" >> "$LOGFILE" 2>&1 &
  echo "$!" > "$PIDFILE"
  sleep 2
  if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "[opencode-web] 已后台启动 (PID $(cat "$PIDFILE"))"
    echo "[opencode-web] 界面: http://$BIND_HOST:$PORT  密码: $OPENCODE_SERVER_PASSWORD"
  if [ -n "${VSCODE_PROXY_URI:-}" ]; then
    echo "[opencode-web] 外网入口: ${VSCODE_PROXY_URI//\{\{port\}\}/$PORT}"
  fi
    echo "[opencode-web] 日志: $LOGFILE   停止: $0 环境里 STOP=1 再跑一次"
  else
    echo "[opencode-web] 启动失败, 日志: $LOGFILE" >&2
    exit 1
  fi
fi