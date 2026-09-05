#!/usr/bin/env bash
#
# 启动控制台后端（FastAPI + Tortoise）。
#
# 用法:
#   ./start-backend.sh                 # 初始化库并启动(带热重载)
#   CREATE_ADMIN=1 ./start-backend.sh  # 顺便创建管理员(默认用户名 admin)
#   RESET_ADMIN=1 ADMIN_PASSWORD=xxxxxxxxxxxx ./start-backend.sh  # 忘记密码时重置管理员
#   HOST=0.0.0.0 PORT=8000 RELOAD=0 ./start-backend.sh
#   CHECK_ONLY=1 ./start-backend.sh    # 只做环境/密钥/建库检查, 不启动服务
#
# 可用环境变量覆盖:
#   DATABASE_URL          默认 sqlite://db.sqlite3 (生产设为 postgres://...)
#   HOST / PORT           默认 127.0.0.1 / 8000
#   RELOAD                默认 1 (热重载; 生产建议 0)
#   SPARK_SECURE_COOKIES  默认 false (本地 http; 生产 https 设 true)
#   SPARK_EMAIL_ENABLED   默认 false (设 true 需 RESEND_API_KEY/RESEND_FROM 等)
#   密钥若未通过环境提供, 首次运行会在 .secrets/ 下生成并复用(重启不掉登录)。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ---- Python 解释器: 优先用项目 venv ----
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="$(command -v python3 || command -v python)"
fi
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# ---- 基本配置(可被环境变量覆盖) ----
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-1}"
export DATABASE_URL="${DATABASE_URL:-sqlite://db.sqlite3}"
export SPARK_SECURE_COOKIES="${SPARK_SECURE_COOKIES:-false}"
export SPARK_EMAIL_ENABLED="${SPARK_EMAIL_ENABLED:-false}"

# ---- 依赖检查 ----
if ! "$PY" -c "import fastapi, uvicorn, tortoise, argon2, cryptography" >/dev/null 2>&1; then
  echo "[start] 缺少后端依赖, 请先安装: $PY -m pip install -r requirements.txt" >&2
  exit 1
fi

# ---- 密钥: 环境优先; 否则在 .secrets/ 下持久化生成(base64 of 32 bytes) ----
SECRETS_DIR="$ROOT/.secrets"
mkdir -p "$SECRETS_DIR"
ensure_key() { # $1=环境变量名 $2=文件名
  local var="$1" file="$SECRETS_DIR/$2"
  if [ -n "${!var:-}" ]; then return; fi
  if [ ! -f "$file" ]; then
    "$PY" -c "import os,base64;open('$file','w').write(base64.b64encode(os.urandom(32)).decode())"
    chmod 600 "$file"
    echo "[start] 已生成密钥 $file"
  fi
  export "$var"="$(cat "$file")"
}
ensure_key SPARK_COOKIE_KEY_B64  cookie.key
ensure_key SPARK_SESSION_KEY_B64 session.key
if [ "$SPARK_EMAIL_ENABLED" = "true" ]; then
  ensure_key SPARK_PII_KEY_B64 pii.key
fi

# ---- 初始化数据库(幂等: 建表 + 部分唯一索引 + 种子) ----
echo "[start] 初始化数据库: $DATABASE_URL"
"$PY" -m core.db

# ---- 可选: 创建 / 重置管理员 ----
#   CREATE_ADMIN=1                创建管理员(已存在则报错跳过)
#   RESET_ADMIN=1                 重置管理员密码(忘记密码自救; 用户名已存在也可用)
#   ADMIN_USER=admin              管理员用户名(默认 admin)
#   ADMIN_PASSWORD=xxxxxxxxxxxx   指定密码(>=12 位; 不填则随机生成并打印)
if [ "${RESET_ADMIN:-0}" = "1" ] || [ "${CREATE_ADMIN:-0}" = "1" ]; then
  ADMIN_ARGS=("${ADMIN_USER:-admin}")
  [ -n "${ADMIN_PASSWORD:-}" ] && ADMIN_ARGS+=(--password "$ADMIN_PASSWORD")
  [ "${RESET_ADMIN:-0}" = "1" ] && ADMIN_ARGS+=(--reset)
  "$PY" -m core create-admin "${ADMIN_ARGS[@]}" || true
fi

if [ "${CHECK_ONLY:-0}" = "1" ]; then
  echo "[start] 检查通过(未启动服务)。"
  exit 0
fi

# ---- 启动 uvicorn ----
RELOAD_FLAG=""
[ "$RELOAD" = "1" ] && RELOAD_FLAG="--reload"
echo "[start] 启动 uvicorn -> http://$HOST:$PORT  (reload=$RELOAD)"
echo "[start] 前端开发: cd panel && npm run dev (已代理 /api -> 127.0.0.1:$PORT)"
exec "$PY" -m uvicorn server.index:app --host "$HOST" --port "$PORT" $RELOAD_FLAG
